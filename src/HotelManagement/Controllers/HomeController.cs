using Microsoft.AspNetCore.Mvc;

namespace HotelManagement.Controllers;

[Route("Home")]
[ResponseCache(NoStore = true, Location = ResponseCacheLocation.None)]
public sealed class HomeController : Controller
{
    [HttpGet]
    public async Task<IActionResult> Index()
    {
        await HttpContext.Session.LoadAsync();
        if (HttpContext.Session.GetInt32("UserId") is null)
            return RedirectToAction("Index", "Login");

        return View();
    }
}
