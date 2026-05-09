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

/// <summary>
/// Implements Jellyfin's <see cref="IChannel"/> interface to surface the
/// jslsd daemon's pending-downloads queue as a browseable channel inside
/// Jellyfin. Channels are Jellyfin's stable, documented mechanism for plugins
/// to expose virtual content — they show up in the user's left-nav as a
/// regular library, with proper iOS/Android/tvOS client support.
///
/// The Channel is read-only and non-playable: items render with their poster
/// (which the daemon overlays with a progress bar) but have no MediaSources.
/// When a download completes, the daemon evicts the item from its queue and
/// the Channel reflects that on next refresh.
/// </summary>
public class SeerrLoadingScreenChannel : IChannel, IHasCacheKey
{
    private readonly DaemonClient _daemon;
    private readonly ILogger<SeerrLoadingScreenChannel> _log;

    public SeerrLoadingScreenChannel(DaemonClient daemon, ILogger<SeerrLoadingScreenChannel> log)
    {
        _daemon = daemon;
        _log = log;
    }

    public string Name =>
        Plugin.Instance?.Configuration.VirtualLibraryName ?? "📥 Coming Soon";

    public string Description =>
        "Pending Sonarr/Radarr downloads with live progress, fed by the jslsd daemon.";

    public string DataVersion => Plugin.Instance?.Configuration.DaemonUrl ?? "v0";

    public string HomePageUrl => "https://github.com/Petr1t/jellyfin_seerr_loading_screen";

    public ChannelParentalRating ParentalRating => ChannelParentalRating.GeneralAudience;

    /// <summary>
    /// Cache key — when this string changes, Jellyfin re-fetches the channel.
    /// We hash the current pending-item IDs + their progress buckets so the
    /// channel refreshes when the queue or progress meaningfully changes.
    /// </summary>
    public string GetCacheKey(string? userId)
    {
        try
        {
            var items = _daemon.ListAsync().GetAwaiter().GetResult();
            var seed = string.Join(
                "|",
                items.Select(i =>
                    $"{i.Id}:{(int)(i.ProgressPercent / 5) * 5}:{i.Status}"
                )
            );
            return Hash(seed);
        }
        catch (Exception e)
        {
            _log.LogWarning("CacheKey computation failed: {Message}", e.Message);
            return DateTime.UtcNow.Ticks.ToString();
        }
    }

    public InternalChannelFeatures GetChannelFeatures()
    {
        return new InternalChannelFeatures
        {
            ContentTypes = new List<ChannelMediaContentType>
            {
                ChannelMediaContentType.Movie,
                ChannelMediaContentType.Episode,
            },
            MediaTypes = new List<ChannelMediaType> { ChannelMediaType.Video },
            DefaultSortFields = new List<ChannelItemSortField>
            {
                ChannelItemSortField.Name,
                ChannelItemSortField.DateCreated,
            },
            SupportsContentDownloading = false,
        };
    }

    public bool IsEnabledFor(string userId) => true;

    public Task<DynamicImageResponse> GetChannelImage(ImageType type, CancellationToken ct)
    {
        return Task.FromResult(new DynamicImageResponse { HasImage = false });
    }

    public IEnumerable<ImageType> GetSupportedChannelImages() => Array.Empty<ImageType>();

    public async Task<ChannelItemResult> GetChannelItems(
        InternalChannelItemQuery query,
        CancellationToken ct
    )
    {
        var pending = await _daemon.ListAsync(ct).ConfigureAwait(false);
        var config = Plugin.Instance?.Configuration ?? new PluginConfiguration();

        var visible = pending
            .Where(i => !(config.HideCompleted && i.Status == "completed"))
            .Where(i =>
                config.ShowAllUsers
                || string.IsNullOrEmpty(query.UserId.ToString())
                || string.IsNullOrEmpty(i.RequestedBy)
                || string.Equals(i.RequestedBy, query.UserId.ToString(), StringComparison.OrdinalIgnoreCase)
            )
            .ToList();

        var items = visible.Select(p => ToChannelItemInfo(p)).ToList();

        return new ChannelItemResult
        {
            Items = items,
            TotalRecordCount = items.Count,
        };
    }

    private ChannelItemInfo ToChannelItemInfo(PendingItem p)
    {
        var displayName = BuildDisplayName(p);
        var overview = BuildOverview(p);
        var contentType = p.Type == "tv"
            ? ChannelMediaContentType.Episode
            : ChannelMediaContentType.Movie;

        return new ChannelItemInfo
        {
            Id = p.Id,
            Name = displayName,
            Type = ChannelItemType.Media,
            ContentType = contentType,
            MediaType = ChannelMediaType.Video,
            Overview = overview,
            ImageUrl = _daemon.PosterUrlFor(p.Id),
            DateCreated = DateTime.UtcNow,
            // No MediaSources → the item is non-playable. Clicking it opens
            // the detail view with poster + overview, which is exactly what
            // a "coming soon" placeholder should be.
            MediaSources = new List<MediaSourceInfo>(),
        };
    }

    private static string BuildDisplayName(PendingItem p)
    {
        if (p.Type == "tv" && p.Season is not null && p.Episode is not null && p.SeriesTitle is not null)
        {
            return $"{p.SeriesTitle} — S{p.Season:D2}E{p.Episode:D2}";
        }
        return p.Title;
    }

    private static string BuildOverview(PendingItem p)
    {
        var sb = new StringBuilder();
        sb.Append(StatusBadge(p.Status));
        sb.Append(" · ");
        sb.AppendFormat("{0:F0}%", p.ProgressPercent);
        if (p.EtaSeconds is { } eta)
        {
            sb.Append(" · ETA ").Append(HumanEta(eta));
        }
        if (!string.IsNullOrEmpty(p.RequestedBy))
        {
            sb.Append("\n\nRequested by ").Append(p.RequestedBy);
        }
        if (!string.IsNullOrEmpty(p.DownloadClient))
        {
            sb.Append("\nDownload client: ").Append(p.DownloadClient);
        }
        return sb.ToString();
    }

    private static string StatusBadge(string status) => status switch
    {
        "downloading" => "🟢 LIVE",
        "queued" => "⚪ QUEUED",
        "completed" => "🔵 READY",
        "failed" => "🔴 FAILED",
        "paused" => "🟡 PAUSED",
        _ => "⚪ PENDING",
    };

    private static string HumanEta(int seconds)
    {
        if (seconds < 60) return $"{seconds}s";
        if (seconds < 3600) return $"{seconds / 60}m";
        var hours = seconds / 3600;
        var minutes = (seconds % 3600) / 60;
        return $"{hours}h {minutes}m";
    }

    private static string Hash(string s)
    {
        var bytes = Encoding.UTF8.GetBytes(s);
        var hash = SHA1.HashData(bytes);
        return Convert.ToHexString(hash)[..16];
    }
}
