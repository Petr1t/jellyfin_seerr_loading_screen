using MediaBrowser.Controller.Plugins;
using Microsoft.Extensions.DependencyInjection;

using Jellyfin.Plugin.SeerrLoadingScreen.Services;

namespace Jellyfin.Plugin.SeerrLoadingScreen;

/// <summary>
/// Registers DaemonClient with Jellyfin's DI container.
/// </summary>
public class ServiceRegistration : IPluginServiceRegistrator
{
    public void RegisterServices(IServiceCollection services)
    {
        services.AddHttpClient<DaemonClient>();
    }
}
