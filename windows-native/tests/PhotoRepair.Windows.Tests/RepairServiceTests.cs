using System.Diagnostics;
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
    public void ReplacingScannedDirectoryWithJunctionIsRefusedBeforeWrite()
    {
        string originalPath = Make("album/IMG_20240321_174532.jpg");
        var reader = new MetadataReader();
        var service = new RepairService(root, reader);
        var plan = RepairPlanner.Plan(reader.ReadFile(originalPath), RepairPlanner.FindMethod("modified:filename"));
        string album = Path.GetDirectoryName(originalPath)!;
        string outside = Path.Combine(Path.GetTempPath(), "PhotoRepair.Outside", Guid.NewGuid().ToString("N"));
        string target = Path.Combine(outside, "album-target");
        Directory.CreateDirectory(outside);
        Directory.Move(album, target);
        CreateJunction(album, target);
        string redirectedPath = Path.Combine(target, Path.GetFileName(originalPath));
        DateTime before = File.GetLastWriteTimeUtc(redirectedPath);

        try
        {
            var result = service.Apply(plan, createBackup: false);

            Assert.False(result.Success);
            Assert.Contains("junction or symbolic link", result.Status);
            Assert.Equal(before, File.GetLastWriteTimeUtc(redirectedPath));
        }
        finally
        {
            if (Directory.Exists(album)) Directory.Delete(album);
            if (Directory.Exists(outside)) Directory.Delete(outside, true);
        }
    }

    [Fact]
    public void BackupDirectoryJunctionIsRefusedBeforeSourceModification()
    {
        string path = Make();
        var reader = new MetadataReader();
        var service = new RepairService(root, reader);
        var plan = RepairPlanner.Plan(reader.ReadFile(path), RepairPlanner.FindMethod("created:filename"));
        DateTime before = File.GetCreationTimeUtc(path);
        string outside = Path.Combine(Path.GetTempPath(), "PhotoRepair.BackupOutside", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(outside);
        CreateJunction(service.BackupRoot, outside);

        try
        {
            var result = service.Apply(plan);

            Assert.False(result.Success);
            Assert.Contains("junction or symbolic link", result.Status);
            Assert.Equal(before, File.GetCreationTimeUtc(path));
            Assert.Empty(Directory.EnumerateFileSystemEntries(outside));
        }
        finally
        {
            if (Directory.Exists(service.BackupRoot)) Directory.Delete(service.BackupRoot);
            if (Directory.Exists(outside)) Directory.Delete(outside, true);
        }
    }

    [Fact]
    public void PostWriteLoggingFailureRollsBackFilesystemRepairWithoutBackup()
    {
        string path = Make();
        var reader = new MetadataReader();
        var service = new RepairService(root, reader);
        var plan = RepairPlanner.Plan(reader.ReadFile(path), RepairPlanner.FindMethod("created:filename"));
        DateTime created = File.GetCreationTimeUtc(path);
        DateTime modified = File.GetLastWriteTimeUtc(path);
        Directory.CreateDirectory(service.LogPath); // Force the audit append to fail after the write.

        var result = service.Apply(plan, createBackup: false);

        Assert.False(result.Success);
        Assert.Equal(created, File.GetCreationTimeUtc(path));
        Assert.Equal(modified, File.GetLastWriteTimeUtc(path));
    }

    [Fact]
    public void PostWriteVerificationFailureRestoresMetadataFileBytesWithoutBackup()
    {
        string path = Make();
        byte[] original = File.ReadAllBytes(path);
        var reader = new MetadataReader();
        var service = new RepairService(root, reader, new CorruptingNoOpTakenWriter());
        var plan = RepairPlanner.Plan(reader.ReadFile(path), RepairPlanner.FindMethod("taken:filename"));
        DateTime created = File.GetCreationTimeUtc(path);
        DateTime modified = File.GetLastWriteTimeUtc(path);
        DateTime accessed = File.GetLastAccessTimeUtc(path);

        var result = service.Apply(plan, createBackup: false);

        Assert.False(result.Success);
        Assert.Contains("did not produce the value", result.Status);
        Assert.Equal(created, File.GetCreationTimeUtc(path));
        Assert.Equal(modified, File.GetLastWriteTimeUtc(path));
        Assert.Equal(accessed, File.GetLastAccessTimeUtc(path));
        Assert.Equal(original, File.ReadAllBytes(path));
    }

    [Fact]
    public void TakenRepairRestoresAllFilesystemTimesWhenWriterFailsAfterTouchingThem()
    {
        string path = Make();
        var reader = new MetadataReader();
        var service = new RepairService(root, reader, new FailingTouchingTakenWriter());
        var plan = RepairPlanner.Plan(reader.ReadFile(path), RepairPlanner.FindMethod("taken:filename"));
        DateTime created = File.GetCreationTimeUtc(path);
        DateTime modified = File.GetLastWriteTimeUtc(path);
        DateTime accessed = File.GetLastAccessTimeUtc(path);

        var result = service.Apply(plan, createBackup: false);

        Assert.False(result.Success);
        Assert.Contains("simulated metadata failure", result.Status);
        Assert.Equal(created, File.GetCreationTimeUtc(path));
        Assert.Equal(modified, File.GetLastWriteTimeUtc(path));
        Assert.Equal(accessed, File.GetLastAccessTimeUtc(path));
        Assert.Contains("ERROR (no backup)", File.ReadAllText(service.LogPath));
    }

    [Fact]
    public void MissingTakenIsAddedWithoutChangingJpegScanData()
    {
        string path = Path.Combine(root, "IMG_20240321_174532.jpg");
        File.Copy(Path.Combine(AppContext.BaseDirectory, "Fixtures", "empty.jpg"), path);
        File.SetCreationTime(path, new DateTime(2024, 3, 21, 18, 0, 0));
        File.SetLastWriteTime(path, new DateTime(2024, 3, 21, 19, 0, 0));
        var reader = new MetadataReader();
        var plan = RepairPlanner.Plan(reader.ReadFile(path), RepairPlanner.FindMethod("taken:filename"));
        byte[] beforeScanData = FromStartOfScan(File.ReadAllBytes(path));
        DateTime created = File.GetCreationTimeUtc(path);
        DateTime modified = File.GetLastWriteTimeUtc(path);
        DateTime accessed = File.GetLastAccessTimeUtc(path);

        var result = new RepairService(root, reader).Apply(plan, createBackup: false);

        Assert.True(result.Success, result.Status);
        Assert.Equal(created, File.GetCreationTimeUtc(path));
        Assert.Equal(modified, File.GetLastWriteTimeUtc(path));
        Assert.Equal(accessed, File.GetLastAccessTimeUtc(path));
        Assert.Equal("2024-03-21 17:45:32", reader.ReadTaken(path));
        Assert.Equal("2024-03-21 17:45:32", result.RefreshedRecord?.Taken);
        Assert.Equal(beforeScanData, FromStartOfScan(File.ReadAllBytes(path)));
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

    private static void CreateJunction(string link, string target)
    {
        var start = new ProcessStartInfo("cmd.exe")
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true
        };
        start.ArgumentList.Add("/c");
        start.ArgumentList.Add("mklink");
        start.ArgumentList.Add("/J");
        start.ArgumentList.Add(link);
        start.ArgumentList.Add(target);
        using Process process = Process.Start(start)
            ?? throw new Xunit.Sdk.XunitException("Could not start mklink.");
        string output = process.StandardOutput.ReadToEnd();
        string error = process.StandardError.ReadToEnd();
        process.WaitForExit();
        Assert.True(process.ExitCode == 0, $"mklink failed: {output} {error}");
    }

    private static byte[] FromStartOfScan(byte[] jpeg)
    {
        for (int i = 0; i < jpeg.Length - 1; i++)
            if (jpeg[i] == 0xFF && jpeg[i + 1] == 0xDA)
                return jpeg[i..];
        throw new Xunit.Sdk.XunitException("JPEG fixture has no start-of-scan marker.");
    }

    private sealed class CorruptingNoOpTakenWriter : ITakenMetadataWriter
    {
        public void WriteTaken(string path, DateTimeOffset timestamp) => File.WriteAllText(path, "corrupted");
    }

    private sealed class FailingTouchingTakenWriter : ITakenMetadataWriter
    {
        public void WriteTaken(string path, DateTimeOffset timestamp)
        {
            var changed = new DateTime(2001, 2, 3, 4, 5, 6, DateTimeKind.Utc);
            File.SetCreationTimeUtc(path, changed);
            File.SetLastWriteTimeUtc(path, changed);
            File.SetLastAccessTimeUtc(path, changed);
            throw new IOException("simulated metadata failure");
        }
    }
}
