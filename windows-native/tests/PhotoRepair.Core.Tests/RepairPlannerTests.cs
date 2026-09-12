using PhotoRepair.Core;

namespace PhotoRepair.Core.Tests;

public sealed class RepairPlannerTests
{
    private static MediaRecord Record(
        string path = @"C:\photos\IMG_20240321_174532.jpg",
        string taken = "",
        string? takenAt = null,
        string? filenameAt = "2024-03-21 17:45:32",
        string createdAt = "2024-03-21 18:00:00",
        string modifiedAt = "2024-03-21 19:00:00") =>
        new(path, "image", 100,
            Timestamps.Parse(createdAt)!.Value,
            Timestamps.Parse(modifiedAt)!.Value,
            taken,
            Timestamps.Parse(takenAt),
            Timestamps.Parse(filenameAt));

    [Fact]
    public void UnavailableSourceIsSkipped()
    {
        var method = RepairPlanner.FindMethod("created:taken");
        var item = RepairPlanner.Plan(Record(takenAt: null), method);

        Assert.False(item.Applicable);
        Assert.Contains("not available", item.SkipReason);
    }

    [Fact]
    public void ExistingDestinationValueIsSkipped()
    {
        var method = RepairPlanner.FindMethod("modified:filename");
        var item = RepairPlanner.Plan(
            Record(filenameAt: "2024-03-21 19:00:00"), method);

        Assert.False(item.Applicable);
        Assert.Contains("already equals", item.SkipReason);
    }

    [Fact]
    public void TakenRepairIsJpegOnly()
    {
        var method = RepairPlanner.FindMethod("taken:filename");
        var item = RepairPlanner.Plan(
            Record(path: @"C:\photos\IMG_20240321_174532.png"), method);

        Assert.False(item.Applicable);
        Assert.Contains("JPEG", item.SkipReason);
    }

    [Fact]
    public void MissingTakenShowsExplicitBeforeValue()
    {
        var method = RepairPlanner.FindMethod("taken:filename");
        var item = RepairPlanner.Plan(Record(), method);

        Assert.True(item.Applicable);
        Assert.Equal("(missing)", item.Before);
        Assert.Equal("2024-03-21 17:45:32", item.After);
    }

    [Fact]
    public void PreviewNeverShowsMoreThanTenExamples()
    {
        var method = RepairPlanner.FindMethod("created:filename");
        var records = Enumerable.Range(0, 25)
            .Select(i => Record(path: $@"C:\photos\IMG_20240321_1745{i:00}.jpg"))
            .ToArray();

        var preview = RepairPlanner.Preview(records, method, 100);

        Assert.Equal(25, preview.SelectedCount);
        Assert.Equal(25, preview.ApplicableCount);
        Assert.Equal(10, preview.Examples.Count);
    }
}
