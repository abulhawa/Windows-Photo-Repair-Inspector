using System.Text;
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
        Assert.Equal("2024-03-21 18:00:00", result.RefreshedRecord?.Taken);
        Assert.Equal(beforeScanData, FromStartOfScan(File.ReadAllBytes(path)));
        Assert.Equal(created, File.GetCreationTimeUtc(path));
        Assert.Equal(modified, File.GetLastWriteTimeUtc(path));
        Assert.Equal(accessed, File.GetLastAccessTimeUtc(path));
    }

    [Fact]
    public void JpegWithoutExifGetsMinimalExifWithoutChangingScanData()
    {
        string path = Path.Combine(root, "IMG_20240321_174532.jpg");
        byte[] source = File.ReadAllBytes(Path.Combine(AppContext.BaseDirectory, "Fixtures", "empty.jpg"));
        byte[] noExif = RemoveExifApp1(source);
        File.WriteAllBytes(path, noExif);
        File.SetCreationTime(path, new DateTime(2024, 3, 21, 18, 0, 0));
        File.SetLastWriteTime(path, new DateTime(2024, 3, 21, 19, 0, 0));

        var reader = new MetadataReader();
        Assert.Null(reader.ReadTaken(path));
        byte[] beforeScanData = FromStartOfScan(File.ReadAllBytes(path));
        var plan = RepairPlanner.Plan(reader.ReadFile(path), RepairPlanner.FindMethod("taken:filename"));

        var result = new RepairService(root, reader).Apply(plan, createBackup: false);

        Assert.True(result.Success, result.Status);
        Assert.Equal("2024-03-21 17:45:32", reader.ReadTaken(path));
        Assert.Equal(beforeScanData, FromStartOfScan(File.ReadAllBytes(path)));
    }

    private static byte[] RemoveExifApp1(byte[] jpeg)
    {
        byte[] signature = Encoding.ASCII.GetBytes("Exif\0\0");
        int signatureAt = IndexOf(jpeg, signature);
        if (signatureAt < 4 || jpeg[signatureAt - 4] != 0xFF || jpeg[signatureAt - 3] != 0xE1)
            throw new Xunit.Sdk.XunitException("JPEG fixture has no EXIF APP1 segment.");

        int markerAt = signatureAt - 4;
        int length = (jpeg[markerAt + 2] << 8) | jpeg[markerAt + 3];
        int segmentBytes = checked(length + 2); // Marker bytes plus JPEG length field/payload.
        int tailAt = checked(markerAt + segmentBytes);
        if (length < 8 || tailAt > jpeg.Length)
            throw new Xunit.Sdk.XunitException("JPEG fixture has an invalid EXIF APP1 length.");

        byte[] result = new byte[jpeg.Length - segmentBytes];
        Buffer.BlockCopy(jpeg, 0, result, 0, markerAt);
        Buffer.BlockCopy(jpeg, tailAt, result, markerAt, jpeg.Length - tailAt);
        return result;
    }

    private static int IndexOf(byte[] data, byte[] pattern)
    {
        for (int i = 0; i <= data.Length - pattern.Length; i++)
        {
            bool match = true;
            for (int j = 0; j < pattern.Length; j++)
                if (data[i + j] != pattern[j]) { match = false; break; }
            if (match) return i;
        }
        return -1;
    }

    private static byte[] FromStartOfScan(byte[] jpeg)
    {
        for (int i = 0; i < jpeg.Length - 1; i++)
            if (jpeg[i] == 0xFF && jpeg[i + 1] == 0xDA)
                return jpeg[i..];
        throw new Xunit.Sdk.XunitException("JPEG fixture has no start-of-scan marker.");
    }
}
