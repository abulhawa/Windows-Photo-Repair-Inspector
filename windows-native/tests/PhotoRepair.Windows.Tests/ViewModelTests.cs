using PhotoRepair.Core;

namespace PhotoRepair.Windows.Tests;

public sealed class ViewModelTests : IDisposable
{
    private readonly string root = Path.Combine(Path.GetTempPath(), "PhotoRepair.ViewModel", Guid.NewGuid().ToString("N"));
    public ViewModelTests() => Directory.CreateDirectory(root);
    public void Dispose() => Directory.Delete(root, true);
    [Fact]
    public async Task ScanFilterSortAndSelectionShareOneModel()
    {
        File.WriteAllText(Path.Combine(root, "missing.jpg"), "bad image");
        File.Copy(Path.Combine(AppContext.BaseDirectory, "Fixtures", "nested.jpg"), Path.Combine(root, "taken.jpg"));
        File.WriteAllText(Path.Combine(root, "movie.mp4"), "video");
        var model = new InspectionViewModel(a => a());
        await model.ScanAsync(root);
        Assert.False(model.IsScanning);
        Assert.Equal(3, model.Rows.Count);
        Assert.Equal("Scan complete", model.ProgressText);
        model.View = "Review"; model.Refresh();
        Assert.Equal("missing.jpg", Assert.Single(model.Rows).Record.Name);
        model.SelectAll(); Assert.Single(model.Selection.Selected);
        model.View = "Library"; model.Search = "TAKEN"; model.Refresh();
        Assert.Empty(model.Selection.Selected);
        Assert.Equal("taken.jpg", Assert.Single(model.Rows).Record.Name);
        model.Search = ""; model.Media = "video"; model.Refresh();
        Assert.Equal("movie.mp4", Assert.Single(model.Rows).Record.Name);
        model.Media = "All"; model.Refresh(); model.Sort("Size");
        Assert.Equal(model.Rows.Select(r => r.Record.SizeBytes).Order(), model.Rows.Select(r => r.Record.SizeBytes));
        model.SelectAll(); model.Sort("Size"); Assert.Equal(3, model.Selection.Selected.Count);
    }
    [Fact]
    public async Task FailedScanKeepsPreviousResultsAndReenablesScan()
    {
        File.WriteAllText(Path.Combine(root, "a.jpg"), "fixture");
        var model = new InspectionViewModel(a => a());
        await model.ScanAsync(root);
        await model.ScanAsync(Path.Combine(root, "missing"));
        Assert.Single(model.Rows);
        Assert.True(model.CanScan);
        Assert.StartsWith("Scan failed:", model.Status);
    }
}
