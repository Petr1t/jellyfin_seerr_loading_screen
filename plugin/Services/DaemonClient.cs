using System;
using System.Net.Http;
using System.Net.Http.Json;
using System.Text.Json.Serialization;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;

namespace Jellyfin.Plugin.SeerrLoadingScreen.Services;

/// <summary>
/// HTTP client to the jslsd Python daemon.
/// </summary>
public class DaemonClient
{
    private readonly HttpClient _http;
    private readonly ILogger<DaemonClient> _log;

    public DaemonClient(HttpClient http, ILogger<DaemonClient> log)
    {
        _http = http;
        _log = log;
        _http.Timeout = TimeSpan.FromSeconds(10);
    }

    public async Task<PendingItem[]> ListAsync(CancellationToken ct = default)
    {
        var baseUrl = (Plugin.Instance?.Configuration.DaemonUrl ?? "http://localhost:7000")
            .TrimEnd('/');
        var url = $"{baseUrl}/api/coming-soon";

        try
        {
            var items = await _http.GetFromJsonAsync<PendingItem[]>(url, ct).ConfigureAwait(false);
            return items ?? Array.Empty<PendingItem>();
        }
        catch (Exception e) when (e is HttpRequestException or TaskCanceledException)
        {
            _log.LogWarning("jslsd unreachable at {Url}: {Message}", url, e.Message);
            return Array.Empty<PendingItem>();
        }
    }

    public string PosterUrlFor(string itemId)
    {
        var baseUrl = (Plugin.Instance?.Configuration.DaemonUrl ?? "http://localhost:7000")
            .TrimEnd('/');
        return $"{baseUrl}/api/poster/{itemId}.png";
    }
}

/// <summary>
/// Mirrors jslsd.models.PendingItem.
/// </summary>
public class PendingItem
{
    [JsonPropertyName("id")] public string Id { get; set; } = string.Empty;
    [JsonPropertyName("source")] public string Source { get; set; } = string.Empty;
    [JsonPropertyName("type")] public string Type { get; set; } = string.Empty;
    [JsonPropertyName("title")] public string Title { get; set; } = string.Empty;
    [JsonPropertyName("series_title")] public string? SeriesTitle { get; set; }
    [JsonPropertyName("season")] public int? Season { get; set; }
    [JsonPropertyName("episode")] public int? Episode { get; set; }
    [JsonPropertyName("tmdb_id")] public int? TmdbId { get; set; }
    [JsonPropertyName("tvdb_id")] public int? TvdbId { get; set; }
    [JsonPropertyName("imdb_id")] public string? ImdbId { get; set; }
    [JsonPropertyName("size_total_bytes")] public long SizeTotalBytes { get; set; }
    [JsonPropertyName("size_left_bytes")] public long SizeLeftBytes { get; set; }
    [JsonPropertyName("progress_percent")] public double ProgressPercent { get; set; }
    [JsonPropertyName("eta_seconds")] public int? EtaSeconds { get; set; }
    [JsonPropertyName("download_client")] public string DownloadClient { get; set; } = string.Empty;
    [JsonPropertyName("status")] public string Status { get; set; } = string.Empty;
    [JsonPropertyName("requested_by")] public string? RequestedBy { get; set; }
    [JsonPropertyName("poster_url")] public string PosterUrl { get; set; } = string.Empty;
}
