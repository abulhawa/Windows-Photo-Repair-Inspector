using PhotoRepair.Core;

namespace PhotoRepair.Windows.Tests;

public sealed class AdapterTests : IDisposable
{
    private readonly string root = Path.Combine(Path.GetTempPath(), "PhotoRepair.Tests", Guid.NewGuid().ToString("N"));
    public AdapterTests() => Directory.CreateDirectory(root);
    public void Dispose() => Directory.Delete(root, true);
    private string Make(string name)
    {
        string path = Path.GetFullPath(Path.Combine(root, name));
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        File.WriteAllText(path, "fixture");
        return path;
    }
    [Theory]
    [InlineData("nested.jpg", "2024-03-21 17:45:32")]
    [InlineData("digitized.jpg", "2024-03-21 17:45:33")]
    [InlineData("fallback.jpg", "2024-03-21 18:00:00")]
    [InlineData("empty.jpg", null)]
    public void GeneratedExifIsReadWithoutWriting(string name, string? expected)
    {
        string path = Path.GetFullPath(Path.Combine(root, name));
        File.Copy(Path.Combine(AppContext.BaseDirectory, "Fixtures", name), path);
        var bytes = File.ReadAllBytes(path);
        var created = File.GetCreationTimeUtc(path);
        var modified = File.GetLastWriteTimeUtc(path);
        Assert.Equal(expected, new MetadataReader().ReadTaken(path));
        Assert.Equal(bytes, File.ReadAllBytes(path));
        Assert.Equal(created, File.GetCreationTimeUtc(path));
        Assert.Equal(modified, File.GetLastWriteTimeUtc(path));
    }
    [Fact]
    public void FilesystemTimesAndUnreadableMetadata()
    {
        string path = Make("IMG_20240321_174532.jpg");
        var r = new MetadataReader().ReadFile(path);
        Assert.Equal(File.GetCreationTimeUtc(path), r.CreatedAt.UtcDateTime);
        Assert.Equal(File.GetLastWriteTimeUtc(path), r.ModifiedAt.UtcDateTime);
        Assert.Equal("2024-03-21 17:45:32", r.FilenameDate);
        Assert.Equal("", r.Taken);
        Assert.Equal(new[] { "Missing Taken At" }, r.Issues);
    }
    [Fact]
    public void DiscoveryIncludesAllSupportedTypesAndExcludesNestedBackups()
    {
        var expected = MediaRules.ImageExtensions.Concat(MediaRules.VideoExtensions).Select((e, i) => Make($"nested/file{i}{e.ToUpperInvariant()}")).ToArray();
        Make("ignore.txt"); Make(".photo-repair-backups/old.jpg"); Make("nested/.photo-repair-backups/deeper/old.jpg");
        Assert.Equal(expected.Order(), MediaScanner.Discover(root).Order());
    }
    [Fact]
    public async Task ConcurrentScanPreservesDiscoveryOrderAndExactProgress()
    {
        for (int i = 0; i < 12; i++) Make($"{i}.jpg");
        var paths = MediaScanner.Discover(root).ToArray();
        int active = 0, peak = 0;
        var gate = new object();
        List<ScanProgress> updates = [];
        var scanner = new MediaScanner(3, async (path, token) =>
        {
            lock (gate) { active++; peak = Math.Max(peak, active); }
            await Task.Delay(path == paths[0] ? 100 : 5, token);
            lock (gate) active--;
            return new MetadataReader().ReadFile(path);
        });
        var result = await scanner.ScanAsync(root, updates.Add);
        Assert.Equal(paths, result.Select(r => r.Path));
        Assert.InRange(peak, 2, 3);
        Assert.Equal(Enumerable.Range(0, 13), updates.Select(p => p.Completed));
        Assert.All(updates, p => Assert.Equal(12, p.Total));
    }
    [Fact]
    public async Task CancellationReturnsCompletedPartialResults()
    {
        for (int i = 0; i < 20; i++) Make($"{i}.jpg");
        using var cancel = new CancellationTokenSource();
        var scanner = new MediaScanner(1);
        var result = await scanner.ScanAsync(root, p => { if (p.Completed == 3) cancel.Cancel(); }, cancel.Token);
        Assert.Equal(3, result.Count);
        Assert.Equal(MediaScanner.Discover(root).Take(3), result.Select(r => r.Path));
    }
    [Fact]
    public async Task PreCancelledScanDoesNoMetadataWork()
    {
        Make("a.jpg");
        using var cancel = new CancellationTokenSource(); cancel.Cancel();
        var scanner = new MediaScanner(reader: (_, _) => throw new Xunit.Sdk.XunitException("Must not read"));
        List<ScanProgress> updates = [];
        Assert.Empty(await scanner.ScanAsync(root, updates.Add, cancel.Token));
        Assert.Equal(new[] { new ScanProgress(0, 0) }, updates);
    }
    [Fact]
    public async Task PerFileFailureDoesNotAbortAndStillCountsProgress()
    {
        Make("bad.jpg"); Make("good.jpg");
        List<ScanProgress> updates = [];
        var scanner = new MediaScanner(reader: (path, _) => path.EndsWith("bad.jpg", StringComparison.Ordinal)
            ? throw new IOException("Simulated disappearing file") : Task.FromResult<MediaRecord?>(new MetadataReader().ReadFile(path)));
        var result = await scanner.ScanAsync(root, updates.Add);
        Assert.Equal("good.jpg", Assert.Single(result).Name);
        Assert.Equal(new ScanProgress(2, 2), updates[^1]);
    }
}

