using MediaBrowser.Controller;
using MediaBrowser.Controller.Channels;
using MediaBrowser.Controller.Plugins;
using Microsoft.Extensions.DependencyInjection;

namespace Jellyfin.Plugin.SeerrLoadingScreen;

/// <summary>
/// Registers the DaemonClient, the Channel implementation, and the cache-key
/// refresh background service with Jellyfin's DI container.
///
/// Jellyfin discovers channels via <c>IServiceProvider.GetServices&lt;IChannel&gt;()</c>,
/// so the channel must be registered as a DI service explicitly — there is no
/// assembly scan. We register the concrete type as a singleton and forward
/// <c>IChannel</c> to the same instance, so <see cref="CacheKeyRefreshService"/>
/// can inject the concrete type and share state with the IChannel Jellyfin uses.
/// </summary>
public class ServiceRegistration : IPluginServiceRegistrator
{
    public void RegisterServices(IServiceCollection services, IServerApplicationHost applicationHost)
    {
        services.AddHttpClient<DaemonClient>();
        services.AddSingleton<SeerrLoadingScreenChannel>();
        services.AddSingleton<IChannel>(sp => sp.GetRequiredService<SeerrLoadingScreenChannel>());
        services.AddHostedService<CacheKeyRefreshService>();
    }
}
