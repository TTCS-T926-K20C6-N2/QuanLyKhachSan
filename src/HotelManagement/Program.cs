using HotelManagement.Data;
using HotelManagement.Models;
using Microsoft.AspNetCore.Http.Features;
using Microsoft.AspNetCore.Identity;
using Microsoft.EntityFrameworkCore;

var builder = WebApplication.CreateBuilder(args);

builder.Services.AddControllersWithViews();
builder.Services.AddDbContext<AppDbContext>(options =>
    options.UseSqlite(builder.Configuration.GetConnectionString("DefaultConnection")));
builder.Services.AddScoped<PasswordHasher<User>>();
builder.Services.AddDistributedMemoryCache();
builder.Services.AddSession(options =>
{
    options.IdleTimeout = TimeSpan.FromMinutes(30);
    options.Cookie.Name = "HotelManagement.Session";
    options.Cookie.HttpOnly = true;
    options.Cookie.SecurePolicy = CookieSecurePolicy.Always;
    options.Cookie.SameSite = SameSiteMode.Lax;
    options.Cookie.IsEssential = true;
});
builder.Services.AddAntiforgery(options =>
    options.Cookie.SecurePolicy = CookieSecurePolicy.Always);
builder.Services.Configure<FormOptions>(options => options.ValueLengthLimit = 16384);

var app = builder.Build();

// Credentials are only seeded in Development, and only after migrations were applied.
if (app.Environment.IsDevelopment())
{
    using var scope = app.Services.CreateScope();
    var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
    var email = app.Configuration["DemoUser:Email"]?.Trim();
    var password = app.Configuration["DemoUser:Password"];
    if (!string.IsNullOrWhiteSpace(email))
    {
        var normalizedEmail = email.ToLowerInvariant();
        if (!await db.Users.AnyAsync(x => x.NormalizedEmail == normalizedEmail))
        {
            if (string.IsNullOrEmpty(password))
                throw new InvalidOperationException("Set DemoUser:Password before creating the demo account.");
            var user = new User { Email = email, NormalizedEmail = normalizedEmail };
            user.PasswordHash = scope.ServiceProvider.GetRequiredService<PasswordHasher<User>>()
                .HashPassword(user, password);
            db.Users.Add(user);
            await db.SaveChangesAsync();
        }
    }
    else if (!await db.Users.AnyAsync())
    {
        throw new InvalidOperationException("Prepare DemoUser:Email and DemoUser:Password for the empty demo database.");
    }
}

app.UseExceptionHandler(handler => handler.Run(async context =>
{
    context.Response.StatusCode = StatusCodes.Status503ServiceUnavailable;
    context.Response.ContentType = "text/plain; charset=utf-8";
    await context.Response.WriteAsync("Không thể đăng nhập lúc này. Vui lòng thử lại.");
}));
app.UseHttpsRedirection();
app.UseStaticFiles();
app.UseRouting();
app.UseSession();
app.MapControllers();
app.Run();

// Allows the Login integration tests to host the same application.
public partial class Program;
