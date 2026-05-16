using System;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;

namespace Jellyfin.Plugin.SeerrLoadingScreen;

/// <summary>
/// Periodically polls the daemon and refreshes the channel's cache key.
///
/// Without this loop, <see cref="SeerrLoadingScreenChannel.GetCacheKey"/> returns
/// the hash computed by the most recent <c>GetChannelItems</c> call. If that call
/// returned 0 items (e.g. user blocklisted the only pending item), the cache key
/// stays "DA39A3..." (SHA1 of empty) forever — and Jellyfin's cache check then
/// short-circuits before <c>GetChannelItems</c> ever runs again. New downloads
/// added to Sonarr/Radarr afterwards are invisible until Jellyfin restarts.
///
/// This service runs out-of-band, hits the daemon every
/// <see cref="PluginConfiguration.RefreshIntervalSeconds"/>, and bumps
/// <c>_lastDataVersion</c> when the daemon's queue changes.
/// </summary>
public class CacheKeyRefreshService : IHostedService, IAsyncDisposable
{
    private readonly SeerrLoadingScreenChannel _channel;
    private readonly ILogger<CacheKeyRefreshService> _log;
    private CancellationTokenSource? _cts;
    private Task? _loop;

    public CacheKeyRefreshService(
        SeerrLoadingScreenChannel channel,
        ILogger<CacheKeyRefreshService> log)
    {
        _channel = channel;
        _log = log;
    }

    public Task StartAsync(CancellationToken ct)
    {
        _cts = new CancellationTokenSource();
        _loop = Task.Run(() => RunLoopAsync(_cts.Token), CancellationToken.None);
        _log.LogInformation("CacheKeyRefreshService started");
        return Task.CompletedTask;
    }

    public async Task StopAsync(CancellationToken ct)
    {
        if (_cts is null)
        {
            return;
        }

        _cts.Cancel();
        if (_loop is not null)
        {
            try
            {
                await _loop.WaitAsync(ct).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                // Expected on shutdown.
            }
        }

        _log.LogInformation("CacheKeyRefreshService stopped");
    }

    public async ValueTask DisposeAsync()
    {
        if (_cts is not null)
        {
            _cts.Cancel();
            if (_loop is not null)
            {
                try
                {
                    await _loop.ConfigureAwait(false);
                }
                catch (OperationCanceledException)
                {
                    // Expected on shutdown.
                }
            }

            _cts.Dispose();
            _cts = null;
        }

        GC.SuppressFinalize(this);
    }

    private async Task RunLoopAsync(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            // Read interval each iteration so config changes take effect without
            // a restart.
            var seconds = Plugin.Instance?.Configuration.RefreshIntervalSeconds ?? 30;
            seconds = Math.Clamp(seconds, 10, 600);

            try
            {
                await Task.Delay(TimeSpan.FromSeconds(seconds), ct).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                return;
            }

            try
            {
                await _channel.RefreshCacheVersionAsync(ct).ConfigureAwait(false);
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                // Swallow per-iteration failures: daemon may be down, network
                // hiccup, etc. The next tick will retry. Debug-level so a
                // long-down daemon doesn't spam the main log.
                _log.LogDebug(ex, "Cache key refresh tick failed (continuing)");
            }
        }
    }
}
