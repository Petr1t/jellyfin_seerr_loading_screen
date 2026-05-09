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

    public async Task<IReadOnlyList<PendingItem>> ListAsync(CancellationToken ct = default)
    {
        var url = $"{BaseUrl}/api/coming-soon";
        try
        {
            var items = await _http.GetFromJsonAsync<PendingItem[]>(url, ct).ConfigureAwait(false);
            return (IReadOnlyList<PendingItem>?)items ?? Array.Empty<PendingItem>();
        }
        catch (Exception e) when (e is HttpRequestException or TaskCanceledException)
        {
            _log.LogWarning("jslsd unreachable at {Url}: {Message}", url, e.Message);
            return Array.Empty<PendingItem>();
        }
    }

    public string PosterUrlFor(string itemId) => $"{BaseUrl}/api/poster/{itemId}.png";

    private static string BaseUrl =>
        (Plugin.Instance?.Configuration.DaemonUrl ?? "http://localhost:7000").TrimEnd('/');
}
