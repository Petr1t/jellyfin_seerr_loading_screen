using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Net.Http.Json;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;

namespace Jellyfin.Plugin.SeerrLoadingScreen;

/// <summary>
/// Thin HTTP client to the jslsd Python daemon.
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

    public async Task<BlocklistResult> BlocklistAsync(string itemId, CancellationToken ct = default)
    {
        var url = $"{BaseUrl}/api/items/{Uri.EscapeDataString(itemId)}/blocklist";
        try
        {
            using var resp = await _http.PostAsync(url, content: null, ct).ConfigureAwait(false);
            // 200 = clean, 207 = partial. We forward the body as-is either way.
            var body = await resp.Content
                .ReadFromJsonAsync<BlocklistResult>(cancellationToken: ct)
                .ConfigureAwait(false);
            return body ?? new BlocklistResult { Ok = false, Errors = new[] { $"empty body, http={(int)resp.StatusCode}" } };
        }
        catch (Exception e) when (e is HttpRequestException or TaskCanceledException)
        {
            _log.LogWarning(e, "blocklist dispatch failed for {ItemId}", itemId);
            return new BlocklistResult { Ok = false, Errors = new[] { e.Message } };
        }
    }

    public async Task<IReadOnlyList<PendingItem>> ListAsync(CancellationToken ct = default)
    {
        var url = $"{BaseUrl}/api/coming-soon";
        try
        {
            var items = await _http.GetFromJsonAsync<PendingItem[]>(url, ct).ConfigureAwait(false);
            return (IReadOnlyList<PendingItem>?)items ?? Array.Empty<PendingItem>();
        }
        catch (TaskCanceledException e) when (!ct.IsCancellationRequested)
        {
            // HttpClient.Timeout fired (10s) — daemon is up but slow/hung, distinct from caller-side cancel.
            _log.LogWarning(e, "jslsd timed out at {Url} after {TimeoutSeconds}s", url, _http.Timeout.TotalSeconds);
            return Array.Empty<PendingItem>();
        }
        catch (HttpRequestException e)
        {
            _log.LogWarning(e, "jslsd unreachable at {Url} (status={Status})", url, e.StatusCode);
            return Array.Empty<PendingItem>();
        }
    }

    // Cache-busted URLs: query param matches the same 5% progress bucket as the
    // channel's DataVersion hash, so Jellyfin's image cache invalidates in
    // lockstep with channel re-fetches. Without this the URL never changes and
    // Jellyfin keeps serving the very first poster it saw (e.g. 0% while the
    // daemon has long moved to 100%). The daemon ignores unknown query params.
    public string PosterUrlFor(string itemId, double progressPercent, string status)
    {
        var bucket = ((int)(progressPercent / 5)) * 5;
        return $"{BaseUrl}/api/poster/{itemId}.png?v={bucket:D3}{status}";
    }

    public string InfoTileUrlFor(string itemId, string kind, double progressPercent, string status)
    {
        var bucket = ((int)(progressPercent / 5)) * 5;
        return $"{BaseUrl}/api/poster/{itemId}/tile/{kind}.png?v={bucket:D3}{status}";
    }

    private static string BaseUrl =>
        (Plugin.Instance?.Configuration.DaemonUrl ?? "http://localhost:7000").TrimEnd('/');
}

public class BlocklistResult
{
    [System.Text.Json.Serialization.JsonPropertyName("ok")] public bool Ok { get; set; }
    [System.Text.Json.Serialization.JsonPropertyName("succeeded")] public int Succeeded { get; set; }
    [System.Text.Json.Serialization.JsonPropertyName("failed")] public int Failed { get; set; }
    [System.Text.Json.Serialization.JsonPropertyName("errors")] public string[]? Errors { get; set; }
}
