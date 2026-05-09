using MediaBrowser.Controller;
using MediaBrowser.Controller.Plugins;
using Microsoft.Extensions.DependencyInjection;

namespace Jellyfin.Plugin.SeerrLoadingScreen;

/// <summary>
/// Registers the DaemonClient (typed HTTP client) with Jellyfin's DI container.
/// The IChannel implementation is auto-discovered by Jellyfin via assembly scan.
/// </summary>
public class ServiceRegistration : IPluginServiceRegistrator
{
    public void RegisterServices(IServiceCollection services, IServerApplicationHost applicationHost)
    {
        services.AddHttpClient<DaemonClient>();
    }
}
