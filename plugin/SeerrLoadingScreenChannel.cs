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
        // Clicking into a folder item — Jellyfin echoes our own item id back
        // as FolderId. Return zero children so the page renders empty instead
        // of re-listing the whole channel inside the folder.
        if (!string.IsNullOrEmpty(query.FolderId)
            && (query.FolderId.StartsWith("sonarr-", StringComparison.Ordinal)
                || query.FolderId.StartsWith("radarr-", StringComparison.Ordinal)))
        {
            _log.LogDebug("Sub-folder request for {FolderId}, returning empty", query.FolderId);
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
        Id = p.Id,
        Name = DisplayName(p),
        // Folder => Jellyfin does not show a Play button. Clicking opens the
        // (empty) folder view, so we don't try to play a half-downloaded file.
        Type = ChannelItemType.Folder,
        Overview = Overview(p),
        ImageUrl = _daemon.PosterUrlFor(p.Id),
        DateCreated = DateTime.UtcNow,
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
