namespace HotelManagement.Models;

public sealed class User
{
    public int Id { get; set; }
    public string Email { get; set; } = "";
    public string NormalizedEmail { get; set; } = "";
    public string PasswordHash { get; set; } = "";
}
