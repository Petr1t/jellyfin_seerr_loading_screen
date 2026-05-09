using System.Text.Json.Serialization;

namespace Jellyfin.Plugin.SeerrLoadingScreen;

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
