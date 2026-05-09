using System;
using System.Collections.Generic;
using System.Linq;
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
/// Surfaces the jslsd daemon's pending-downloads queue as a Jellyfin channel.
/// </summary>
public class SeerrLoadingScreenChannel : IChannel
{
    private readonly DaemonClient _daemon;
    private readonly ILogger<SeerrLoadingScreenChannel> _log;

    public SeerrLoadingScreenChannel(DaemonClient daemon, ILogger<SeerrLoadingScreenChannel> log)
    {
        _daemon = daemon;
        _log = log;
    }

    public string Name =>
        Plugin.Instance?.Configuration.VirtualLibraryName ?? "Coming Soon";

    public string Description =>
        "Pending Sonarr/Radarr downloads with live progress.";

    public string DataVersion => $"v0.2-{(DateTime.UtcNow.Ticks / TimeSpan.TicksPerMinute)}";

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

    public async Task<ChannelItemResult> GetChannelItems(
        InternalChannelItemQuery query,
        CancellationToken ct)
    {
        var pending = await _daemon.ListAsync(ct).ConfigureAwait(false);
        var config = Plugin.Instance?.Configuration ?? new PluginConfiguration();

        var items = pending
            .Where(p => !(config.HideCompleted && p.Status == "completed"))
            .Where(p => config.ShowAllUsers
                        || string.IsNullOrEmpty(p.RequestedBy)
                        || string.Equals(p.RequestedBy, query.UserId.ToString(), StringComparison.OrdinalIgnoreCase))
            .Select(ToChannelItem)
            .ToList();

        _log.LogDebug("Channel listing: {Count} item(s)", items.Count);

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
        ContentType = p.Type == "tv" ? ChannelMediaContentType.Episode : ChannelMediaContentType.Movie,
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
        "queued"      => "⚪ QUEUED",
        "completed"   => "🔵 READY",
        "failed"      => "🔴 FAILED",
        "paused"      => "🟡 PAUSED",
        _             => "⚪ PENDING",
    };

    private static string HumanEta(int s) =>
        s < 60     ? $"{s}s"
      : s < 3600   ? $"{s / 60}m"
      :              $"{s / 3600}h {(s % 3600) / 60}m";
}
