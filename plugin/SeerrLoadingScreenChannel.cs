using System;
using System.Collections.Generic;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using MediaBrowser.Controller.Channels;
using MediaBrowser.Controller.Providers;
using MediaBrowser.Model.Channels;
using MediaBrowser.Model.Dto;
using MediaBrowser.Model.Entities;
using MediaBrowser.Model.MediaInfo;
using Microsoft.Extensions.Logging;

namespace Jellyfin.Plugin.SeerrLoadingScreen;

/// <summary>Surfaces the jslsd daemon's queue as a Jellyfin channel.</summary>
public class SeerrLoadingScreenChannel : IChannel, IHasCacheKey
{
    private readonly DaemonClient _daemon;
    private readonly ILogger<SeerrLoadingScreenChannel> _log;
    // Reset on every plugin reload so Jellyfin's channel cache is forced to
    // re-fetch at least once after a restart (the per-poll hash takes over
    // from there).
    private string _lastDataVersion = "boot-" + DateTime.UtcNow.Ticks.ToString();

    public SeerrLoadingScreenChannel(DaemonClient daemon, ILogger<SeerrLoadingScreenChannel> log)
    {
        _daemon = daemon;
        _log = log;
    }

    public string Name =>
        Plugin.Instance?.Configuration.VirtualLibraryName ?? "Coming Soon";

    public string Description => "Pending Sonarr/Radarr downloads with live progress.";

    public string DataVersion => _lastDataVersion;

    public string HomePageUrl => "https://github.com/Petr1t/jellyfin_seerr_loading_screen";

    public ChannelParentalRating ParentalRating => ChannelParentalRating.GeneralAudience;

    public InternalChannelFeatures GetChannelFeatures() => new()
    {
        // Declare Movie+Episode content types so Jellyfin keeps the channel
        // visible in the user's library list. The per-item Type=Folder below
        // is what suppresses the play button.
        ContentTypes = new List<ChannelMediaContentType>
        {
            ChannelMediaContentType.Movie,
            ChannelMediaContentType.Episode,
        },
        MediaTypes = new List<ChannelMediaType> { ChannelMediaType.Video },
        SupportsContentDownloading = false,
    };

    public bool IsEnabledFor(string userId) => true;

    public Task<DynamicImageResponse> GetChannelImage(ImageType type, CancellationToken ct) =>
        Task.FromResult(new DynamicImageResponse { HasImage = false });

    public IEnumerable<ImageType> GetSupportedChannelImages() => Array.Empty<ImageType>();

    /// <summary>
    /// Returns the cache key for this user's view. We hash the current item set —
    /// when the queue or progress meaningfully changes, the key changes and Jellyfin
    /// re-fetches. When nothing changed, we return the same key and Jellyfin serves
    /// from its own cache.
    /// </summary>
    public string GetCacheKey(string? userId) => _lastDataVersion;

    public async Task<ChannelItemResult> GetChannelItems(
        InternalChannelItemQuery query,
        CancellationToken ct)
    {
        // Action tile clicked → dispatch the action to the daemon and return
        // a single confirmation tile. Must be checked BEFORE the generic
        // "sonarr-/radarr-" prefix branch since the action id contains the
        // base item id as part of its suffix.
        if (!string.IsNullOrEmpty(query.FolderId)
            && query.FolderId.StartsWith("action-blocklist-", StringComparison.Ordinal))
        {
            return await ExecuteBlocklistAsync(query.FolderId, ct).ConfigureAwait(false);
        }

        // Sub-folder request: Jellyfin echoes our item id back as FolderId. We
        // return a grid of info tiles so the user lands on a useful detail
        // view instead of a blank page.
        if (!string.IsNullOrEmpty(query.FolderId)
            && (query.FolderId.StartsWith("sonarr-", StringComparison.Ordinal)
                || query.FolderId.StartsWith("radarr-", StringComparison.Ordinal)))
        {
            return await BuildDetailViewAsync(query.FolderId, ct).ConfigureAwait(false);
        }

        // Detail tile clicked → terminal, no further children. Without this we
        // would re-list the whole channel inside an info tile.
        if (!string.IsNullOrEmpty(query.FolderId)
            && (query.FolderId.StartsWith("detail-", StringComparison.Ordinal)
                || query.FolderId.StartsWith("done-", StringComparison.Ordinal)))
        {
            return new ChannelItemResult
            {
                Items = Array.Empty<ChannelItemInfo>(),
                TotalRecordCount = 0,
            };
        }

        // Bound the daemon call so a slow/down daemon never hangs the channel render.
        using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        cts.CancelAfter(TimeSpan.FromSeconds(5));

        IReadOnlyList<PendingItem> pending;
        try
        {
            pending = await _daemon.ListAsync(cts.Token).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            _log.LogWarning("Daemon fetch timed out — returning empty channel");
            pending = Array.Empty<PendingItem>();
        }

        var config = Plugin.Instance?.Configuration ?? new PluginConfiguration();

        var filtered = pending
            .Where(p => !(config.HideCompleted && p.Status == "completed"))
            .Where(p => config.ShowAllUsers
                        || string.IsNullOrEmpty(p.RequestedBy)
                        || string.Equals(
                            p.RequestedBy,
                            query.UserId.ToString(),
                            StringComparison.OrdinalIgnoreCase))
            .ToList();

        var items = filtered.Select(ToChannelItem).ToList();

        // Update cache key based on the underlying queue state: id, status,
        // and 5%-bucket progress. Hashing only ids meant size/progress
        // changes never invalidated Jellyfin's channel cache.
        _lastDataVersion = HashPending(filtered);
        _log.LogDebug("Channel listing: {Count} item(s), version={Version}",
            items.Count, _lastDataVersion);

        return new ChannelItemResult
        {
            Items = items,
            TotalRecordCount = items.Count,
        };
    }

    private ChannelItemInfo ToChannelItem(PendingItem p) => new()
    {
        // Include bucket+status in the channel-item Id so Jellyfin treats each
        // version as a new BaseItem and fetches a fresh poster. Without this,
        // Jellyfin caches the very first image it saw and never re-downloads
        // even when the daemon's URL changes (Jellyfin keys image cache by
        // item id, not by URL). The detail-view routes strip the suffix back
        // to the daemon id — see StripVersionSuffix below.
        Id = VersionedId(p),
        Name = DisplayName(p),
        // Folder => Jellyfin does not show a Play button. Clicking opens the
        // detail view we build in BuildDetailViewAsync below.
        Type = ChannelItemType.Folder,
        Overview = Overview(p),
        ImageUrl = _daemon.PosterUrlFor(p.Id, p.ProgressPercent, p.Status),
        DateCreated = DateTime.UtcNow,
    };

    private static string VersionedId(PendingItem p)
    {
        var bucket = ((int)(p.ProgressPercent / 5)) * 5;
        return $"{p.Id}__v__p{bucket:D3}__{p.Status}";
    }

    private static string StripVersionSuffix(string id)
    {
        var idx = id.IndexOf("__v__", StringComparison.Ordinal);
        return idx < 0 ? id : id[..idx];
    }

    private async Task<ChannelItemResult> BuildDetailViewAsync(string folderId, CancellationToken ct)
    {
        using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        cts.CancelAfter(TimeSpan.FromSeconds(5));

        IReadOnlyList<PendingItem> pending;
        try
        {
            pending = await _daemon.ListAsync(cts.Token).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            pending = Array.Empty<PendingItem>();
        }

        var baseId = StripVersionSuffix(folderId);
        var p = pending.FirstOrDefault(x =>
            string.Equals(x.Id, baseId, StringComparison.Ordinal));
        if (p is null)
        {
            _log.LogDebug("Detail view for {FolderId}: item not in daemon cache", folderId);
            return new ChannelItemResult
            {
                Items = Array.Empty<ChannelItemInfo>(),
                TotalRecordCount = 0,
            };
        }

        var tiles = new List<ChannelItemInfo>();
        void Add(string kind, string name, string overview, bool include = true)
        {
            if (!include) return;
            tiles.Add(new ChannelItemInfo
            {
                // Non-matching "detail-" prefix so a click goes back through the
                // main code path (returns empty) rather than re-entering this
                // detail builder recursively. Bucket+status suffix is included
                // so the tile id changes when the underlying state changes —
                // same image-cache trick as VersionedId above.
                Id = $"detail-{p.Id}-{kind}__v__p{((int)(p.ProgressPercent / 5)) * 5:D3}__{p.Status}",
                Name = name,
                Type = ChannelItemType.Folder,
                Overview = overview,
                ImageUrl = _daemon.InfoTileUrlFor(p.Id, kind, p.ProgressPercent, p.Status),
                DateCreated = DateTime.UtcNow,
            });
        }

        Add("status", $"Status: {StatusLabel(p.Status)}",
            "Aktueller Zustand im Download-Client.");
        Add("progress", $"{p.ProgressPercent:F0}% fertig",
            "Fortschritt basierend auf bereits heruntergeladenen Bytes.");
        Add("eta", "ETA " + (p.EtaSeconds is { } e ? HumanEta(e) : "—"),
            "Geschätzte Restzeit laut Download-Client.", include: p.EtaSeconds is not null);

        if (p.SizeTotalBytes > 0)
        {
            var totalGb = p.SizeTotalBytes / 1024.0 / 1024.0 / 1024.0;
            var doneGb = (p.SizeTotalBytes - p.SizeLeftBytes) / 1024.0 / 1024.0 / 1024.0;
            Add("size", $"{doneGb:F1} / {totalGb:F1} GB",
                "Gesamtgröße und bereits gesicherte Daten.");
        }
        Add("client", $"via {p.DownloadClient}",
            "Download-Client, der diesen Job aktiv betreibt.",
            include: !string.IsNullOrEmpty(p.DownloadClient));
        Add("requester", $"Angefragt von {p.RequestedBy}",
            "Jellyseerr-Nutzer, der die Anfrage gestellt hat.",
            include: !string.IsNullOrEmpty(p.RequestedBy));

        // Only stuck items get the action — no point offering blocklist for
        // an active download. "paused" covers Sonarr's 'warning' state
        // (stalled torrents, import-blocked) which is exactly when the user
        // wants to nudge Sonarr to grab a different release.
        if (p.Status is "paused" or "failed")
        {
            var bucket = ((int)(p.ProgressPercent / 5)) * 5;
            tiles.Add(new ChannelItemInfo
            {
                // "action-blocklist-" prefix gets intercepted in GetChannelItems
                // and dispatched to the daemon. Version suffix gives each
                // state its own item id, matching the rest of the channel's
                // image-cache-invalidation strategy.
                Id = $"action-blocklist-{p.Id}__v__p{bucket:D3}__{p.Status}",
                Name = "Blocklisten + neu suchen",
                Type = ChannelItemType.Folder,
                Overview = "Entfernt diesen Download bei Sonarr/Radarr und sperrt das Release. Beim nächsten Such-Lauf wird automatisch ein anderes Release gegriffen.",
                ImageUrl = _daemon.InfoTileUrlFor(p.Id, "blocklist", p.ProgressPercent, p.Status),
                DateCreated = DateTime.UtcNow,
            });
        }

        return new ChannelItemResult
        {
            Items = tiles,
            TotalRecordCount = tiles.Count,
        };
    }

    private async Task<ChannelItemResult> ExecuteBlocklistAsync(string folderId, CancellationToken ct)
    {
        // Strip the "action-blocklist-" prefix and the version suffix to recover
        // the daemon's stable item id.
        const string prefix = "action-blocklist-";
        var withoutPrefix = folderId[prefix.Length..];
        var baseId = StripVersionSuffix(withoutPrefix);

        using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        cts.CancelAfter(TimeSpan.FromSeconds(10));

        var result = await _daemon.BlocklistAsync(baseId, cts.Token).ConfigureAwait(false);
        _log.LogInformation(
            "Blocklist {ItemId}: ok={Ok} succeeded={Succeeded} failed={Failed}",
            baseId, result.Ok, result.Succeeded, result.Failed);

        var confirmation = new ChannelItemInfo
        {
            // Terminal id (no "sonarr-"/"radarr-" prefix) so a click goes
            // straight to the empty branch — there is nothing further to show.
            Id = $"done-blocklist-{baseId}-{DateTime.UtcNow.Ticks}",
            Name = result.Ok
                ? $"{result.Succeeded} Eintrag/Einträge blocklistet"
                : $"Teilweise fehlgeschlagen ({result.Succeeded} ok / {result.Failed} fehler)",
            Type = ChannelItemType.Folder,
            Overview = result.Ok
                ? "Sonarr sucht beim nächsten Cycle nach einem anderen Release."
                : string.Join(" | ", result.Errors ?? Array.Empty<string>()),
            DateCreated = DateTime.UtcNow,
        };
        return new ChannelItemResult
        {
            Items = new[] { confirmation },
            TotalRecordCount = 1,
        };
    }

    private static string StatusLabel(string s) => s switch
    {
        "downloading" => "Lädt",
        "queued" => "In Warteschlange",
        "completed" => "Fertig",
        "failed" => "Fehlgeschlagen",
        "paused" => "Pausiert",
        _ => s,
    };

    private static string DisplayName(PendingItem p) =>
        p.Type == "tv" && p.Season is { } s && p.Episode is { } e && p.SeriesTitle is not null
            ? $"{p.SeriesTitle} — S{s:D2}E{e:D2}"
            : p.Title;

    private static string Overview(PendingItem p)
    {
        var sb = new StringBuilder();
        sb.Append(StatusBadge(p.Status)).Append(" · ");
        sb.AppendFormat("{0:F0}%", p.ProgressPercent);
        if (p.EtaSeconds is { } eta) sb.Append(" · ETA ").Append(HumanEta(eta));
        if (!string.IsNullOrEmpty(p.RequestedBy)) sb.Append("\n\nRequested by ").Append(p.RequestedBy);
        if (!string.IsNullOrEmpty(p.DownloadClient)) sb.Append("\nVia ").Append(p.DownloadClient);
        return sb.ToString();
    }

    private static string StatusBadge(string s) => s switch
    {
        "downloading" => "🟢 LIVE",
        "queued" => "⚪ QUEUED",
        "completed" => "🔵 READY",
        "failed" => "🔴 FAILED",
        "paused" => "🟡 PAUSED",
        _ => "⚪ PENDING",
    };

    private static string HumanEta(int s) =>
          s < 60   ? $"{s}s"
        : s < 3600 ? $"{s / 60}m"
        :            $"{s / 3600}h {(s % 3600) / 60}m";

    /// <summary>Stable hash over (id, status, progress-bucket) — matches the
    /// daemon's poster cache buckets (5% steps), so Jellyfin re-fetches at
    /// the same granularity at which posters change.</summary>
    private static string HashPending(IEnumerable<PendingItem> items)
    {
        var sb = new StringBuilder();
        foreach (var p in items.OrderBy(x => x.Id, StringComparer.Ordinal))
        {
            var bucket = (int)(p.ProgressPercent / 5) * 5;
            sb.Append(p.Id).Append(':').Append(p.Status).Append(':').Append(bucket).Append('|');
        }
        var hash = SHA1.HashData(Encoding.UTF8.GetBytes(sb.ToString()));
        return Convert.ToHexString(hash)[..16];
    }
}
