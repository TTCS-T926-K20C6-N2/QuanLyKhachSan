using HotelManagement.Data;
using HotelManagement.Models;
using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace HotelManagement.Controllers;

[Route("Login")]
[ResponseCache(NoStore = true, Location = ResponseCacheLocation.None)]
public sealed class LoginController(AppDbContext db, PasswordHasher<User> hasher) : Controller
{
    private const string InvalidCredentials = "Email hoặc mật khẩu không đúng";
    // Only used to perform equivalent hash verification when the email is unknown.
    private static readonly User DummyUser = new();
    private static readonly string DummyHash =
        new PasswordHasher<User>().HashPassword(DummyUser, Guid.NewGuid().ToString());

    [HttpGet]
    public IActionResult Index() => View(new LoginViewModel());

    [HttpPost]
    [ValidateAntiForgeryToken]
    [RequestSizeLimit(65536)]
    [RequestFormLimits(ValueLengthLimit = 16384)]
    public async Task<IActionResult> Index(LoginViewModel model)
    {
        var form = await Request.ReadFormAsync();
        if (form["Email"].Count > 1 || form["Password"].Count > 1)
            return BadRequest("Dữ liệu đăng nhập không hợp lệ.");

        if (string.IsNullOrWhiteSpace(model.Email))
            ModelState.AddModelError(nameof(model.Email), "Vui lòng nhập email.");
        if (string.IsNullOrEmpty(model.Password))
            ModelState.AddModelError(nameof(model.Password), "Vui lòng nhập mật khẩu.");
        if (!ModelState.IsValid)
            return View(model);

        var normalizedEmail = model.Email!.Trim().ToLowerInvariant();
        var user = await db.Users.SingleOrDefaultAsync(x => x.NormalizedEmail == normalizedEmail);
        var result = hasher.VerifyHashedPassword(
            user ?? DummyUser, user?.PasswordHash ?? DummyHash, model.Password!);

        if (user is null || result == PasswordVerificationResult.Failed)
        {
            ModelState.AddModelError("", InvalidCredentials);
            return View(model);
        }

        if (result == PasswordVerificationResult.SuccessRehashNeeded)
        {
            user.PasswordHash = hasher.HashPassword(user, model.Password!);
            await db.SaveChangesAsync();
        }

        await HttpContext.Session.LoadAsync();
        HttpContext.Session.SetInt32("UserId", user.Id);
        HttpContext.Session.SetString("UserEmail", user.Email);
        await HttpContext.Session.CommitAsync();
        return RedirectToAction("Index", "Home");
    }
}
