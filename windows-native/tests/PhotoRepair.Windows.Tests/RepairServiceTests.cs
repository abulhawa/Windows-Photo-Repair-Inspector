using PhotoRepair.Core;

namespace PhotoRepair.Windows.Tests;

public sealed class RepairServiceTests : IDisposable
{
    private readonly string root = Path.Combine(Path.GetTempPath(), "PhotoRepair.RepairTests", Guid.NewGuid().ToString("N"));

    public RepairServiceTests() => Directory.CreateDirectory(root);
    public void Dispose() => Directory.Delete(root, true);

    private string Make(string name = "IMG_20240321_174532.jpg", string contents = "original")
    {
        string path = Path.GetFullPath(Path.Combine(root, name));
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        File.WriteAllText(path, contents);
        File.SetCreationTime(path, new DateTime(2024, 3, 21, 18, 0, 0));
        File.SetLastWriteTime(path, new DateTime(2024, 3, 21, 19, 0, 0));
        return path;
    }

    [Fact]
    public void BackupKeepsFirstPreRepairOriginalAndAuditIsWritten()
    {
        string path = Make();
        var reader = new MetadataReader();
        var service = new RepairService(root, reader);
        var first = RepairPlanner.Plan(reader.ReadFile(path), RepairPlanner.FindMethod("created:filename"));

        var result = service.Apply(first);

        Assert.True(result.Success, result.Status);
        string backup = Path.Combine(service.BackupRoot, Path.GetFileName(path));
        Assert.Equal("original", File.ReadAllText(backup));
        Assert.Contains("OK", File.ReadAllText(service.LogPath));

        File.WriteAllText(path, "changed");
        var second = RepairPlanner.Plan(reader.ReadFile(path), RepairPlanner.FindMethod("modified:filename"));
        var secondResult = service.Apply(second);

        Assert.True(secondResult.Success, secondResult.Status);
        Assert.Equal("original", File.ReadAllText(backup));
    }

    [Fact]
    public void BackupCanBeDisabledButAttemptIsStillAudited()
    {
        string path = Make();
        var reader = new MetadataReader();
        var service = new RepairService(root, reader);
        var plan = RepairPlanner.Plan(reader.ReadFile(path), RepairPlanner.FindMethod("created:filename"));

        var result = service.Apply(plan, createBackup: false);

        Assert.True(result.Success, result.Status);
        Assert.False(Directory.Exists(service.BackupRoot));
        Assert.Contains("OK (no backup)", File.ReadAllText(service.LogPath));
    }

    [Fact]
    public void RecordOutsideScanRootIsRefusedAndLogged()
    {
        string path = Path.Combine(Path.GetDirectoryName(root)!, $"outside-{Guid.NewGuid():N}-20240321_174532.jpg");
        File.WriteAllText(path, "outside");
        try
        {
            var reader = new MetadataReader();
            var service = new RepairService(root, reader);
            var plan = RepairPlanner.Plan(reader.ReadFile(path), RepairPlanner.FindMethod("modified:filename"));
            DateTime before = File.GetLastWriteTimeUtc(path);

            var result = service.Apply(plan);

            Assert.False(result.Success);
            Assert.Contains("outside the scanned folder", result.Status);
            Assert.Equal(before, File.GetLastWriteTimeUtc(path));
            Assert.Contains("outside the scanned folder", File.ReadAllText(service.LogPath));
        }
        finally
        {
            File.Delete(path);
        }
    }

    [Fact]
    public void TakenRepairRestoresAllFilesystemTimesEvenIfWriterTouchesThem()
    {
        string path = Make();
        DateTime created = File.GetCreationTimeUtc(path);
        DateTime modified = File.GetLastWriteTimeUtc(path);
        DateTime accessed = File.GetLastAccessTimeUtc(path);
        var reader = new MetadataReader();
        var service = new RepairService(root, reader, new TouchingTakenWriter());
        var plan = RepairPlanner.Plan(reader.ReadFile(path), RepairPlanner.FindMethod("taken:filename"));

        var result = service.Apply(plan, createBackup: false);

        Assert.True(result.Success, result.Status);
        Assert.Equal(created, File.GetCreationTimeUtc(path));
        Assert.Equal(modified, File.GetLastWriteTimeUtc(path));
        Assert.Equal(accessed, File.GetLastAccessTimeUtc(path));
    }

    [Fact]
    public void StalePreviewIsRefusedBeforeModification()
    {
        string path = Make();
        var reader = new MetadataReader();
        var service = new RepairService(root, reader);
        var plan = RepairPlanner.Plan(reader.ReadFile(path), RepairPlanner.FindMethod("created:filename"));
        File.SetCreationTime(path, new DateTime(2024, 3, 21, 17, 45, 33));

        var result = service.Apply(plan);

        Assert.False(result.Success);
        Assert.Contains("changed since the preview", result.Status);
    }

    private sealed class TouchingTakenWriter : ITakenMetadataWriter
    {
        public void WriteTaken(string path, DateTimeOffset timestamp)
        {
            var changed = new DateTime(2001, 2, 3, 4, 5, 6, DateTimeKind.Utc);
            File.SetCreationTimeUtc(path, changed);
            File.SetLastWriteTimeUtc(path, changed);
            File.SetLastAccessTimeUtc(path, changed);
        }
    }
}
