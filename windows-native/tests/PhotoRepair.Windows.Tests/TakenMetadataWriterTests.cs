using PhotoRepair.Core;

namespace PhotoRepair.Windows.Tests;

public sealed class TakenMetadataWriterTests : IDisposable
{
    private readonly string root = Path.Combine(Path.GetTempPath(), "PhotoRepair.TakenWriter", Guid.NewGuid().ToString("N"));

    public TakenMetadataWriterTests() => Directory.CreateDirectory(root);
    public void Dispose() => Directory.Delete(root, true);

    [Fact]
    public void ExistingExifTakenCanBeChangedWithoutChangingJpegScanData()
    {
        string path = Path.Combine(root, "photo.jpg");
        File.Copy(Path.Combine(AppContext.BaseDirectory, "Fixtures", "nested.jpg"), path);
        File.SetCreationTime(path, new DateTime(2024, 3, 21, 18, 0, 0));
        File.SetLastWriteTime(path, new DateTime(2024, 3, 21, 19, 0, 0));

        var reader = new MetadataReader();
        Assert.Equal("2024-03-21 17:45:32", reader.ReadTaken(path));
        byte[] beforeScanData = FromStartOfScan(File.ReadAllBytes(path));
        DateTime created = File.GetCreationTimeUtc(path);
        DateTime modified = File.GetLastWriteTimeUtc(path);
        DateTime accessed = File.GetLastAccessTimeUtc(path);

        var plan = RepairPlanner.Plan(reader.ReadFile(path), RepairPlanner.FindMethod("taken:created"));
        Assert.True(plan.Applicable);

        var result = new RepairService(root, reader).Apply(plan, createBackup: false);

        Assert.True(result.Success, result.Status);
        Assert.Equal("2024-03-21 18:00:00", reader.ReadTaken(path));
        Assert.Equal(beforeScanData, FromStartOfScan(File.ReadAllBytes(path)));
        Assert.Equal(created, File.GetCreationTimeUtc(path));
        Assert.Equal(modified, File.GetLastWriteTimeUtc(path));
        Assert.Equal(accessed, File.GetLastAccessTimeUtc(path));
    }

    private static byte[] FromStartOfScan(byte[] jpeg)
    {
        for (int i = 0; i < jpeg.Length - 1; i++)
            if (jpeg[i] == 0xFF && jpeg[i + 1] == 0xDA)
                return jpeg[i..];
        throw new Xunit.Sdk.XunitException("JPEG fixture has no start-of-scan marker.");
    }
}
