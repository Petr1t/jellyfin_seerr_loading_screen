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
    private string _lastDataVersion = "v0";

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

        var items = pending
            .Where(p => !(config.HideCompleted && p.Status == "completed"))
            .Where(p => config.ShowAllUsers
                        || string.IsNullOrEmpty(p.RequestedBy)
                        || string.Equals(
                            p.RequestedBy,
                            query.UserId.ToString(),
                            StringComparison.OrdinalIgnoreCase))
            .Select(ToChannelItem)
            .ToList();

        // Update cache key based on what we actually returned.
        _lastDataVersion = HashItems(items);
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
        Type = ChannelItemType.Media,
        ContentType = p.Type == "tv"
            ? ChannelMediaContentType.Episode
            : ChannelMediaContentType.Movie,
        MediaType = ChannelMediaType.Video,
        Overview = Overview(p),
        ImageUrl = _daemon.PosterUrlFor(p.Id),
        DateCreated = DateTime.UtcNow,
        MediaSources = new List<MediaSourceInfo>(),
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
    private static string HashItems(IEnumerable<ChannelItemInfo> items)
    {
        var sb = new StringBuilder();
        foreach (var i in items.OrderBy(x => x.Id, StringComparer.Ordinal))
        {
            sb.Append(i.Id).Append('|');
        }
        var hash = SHA1.HashData(Encoding.UTF8.GetBytes(sb.ToString()));
        return Convert.ToHexString(hash)[..16];
    }
}
