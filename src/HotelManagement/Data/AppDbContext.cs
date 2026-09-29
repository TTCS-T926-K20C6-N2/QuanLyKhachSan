using HotelManagement.Models;
using Microsoft.EntityFrameworkCore;

namespace HotelManagement.Data;

public sealed class AppDbContext(DbContextOptions<AppDbContext> options) : DbContext(options)
{
    public DbSet<User> Users => Set<User>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        var user = modelBuilder.Entity<User>();
        user.HasKey(x => x.Id);
        user.Property(x => x.Email).IsRequired();
        user.Property(x => x.NormalizedEmail).IsRequired();
        user.Property(x => x.PasswordHash).IsRequired();
        user.HasIndex(x => x.NormalizedEmail).IsUnique();
    }
}
