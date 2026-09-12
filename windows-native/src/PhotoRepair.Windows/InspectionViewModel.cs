using System.Collections.ObjectModel;
using System.ComponentModel;
using System.IO;
using PhotoRepair.Core;

namespace PhotoRepair.Windows;

public sealed class MediaRow(MediaRecord record) : INotifyPropertyChanged
{
    public MediaRecord Record { get; } = record;
    private bool selected;
    public bool IsSelected { get => selected; internal set { selected = value; PropertyChanged?.Invoke(this, new(nameof(IsSelected))); } }
    public event PropertyChangedEventHandler? PropertyChanged;
}

// UI-agnostic presentation state. The dispatcher is injected by WinUI.
public sealed class InspectionViewModel(Action<Action> dispatch, MediaScanner? scanner = null) : INotifyPropertyChanged
{
    private readonly MediaScanner scanner = scanner ?? new();
    private IReadOnlyList<MediaRecord> records = [];
    private CancellationTokenSource? cancellation;
    private int generation;
    private string? rootPath;
    private bool applying;

    public ObservableCollection<MediaRow> Rows { get; } = [];
    public SelectionModel Selection { get; } = new();
    public IReadOnlyList<RepairMethod> RepairMethods => MediaRules.RepairMethods;
    public string SelectedRepairMethodId { get; private set; } = MediaRules.RepairMethods[0].Id;
    public bool CreateBackup { get; private set; } = true;
    public string Search { get; set; } = "";
    public string Media { get; set; } = "All";
    public string Issue { get; set; } = "All review items";
    public string View { get; set; } = "Library";
    public string? SortColumn { get; private set; }
    public bool Descending { get; private set; }
    public string Status { get; private set; } = "Choose a folder to inspect";
    public string Summary => $"{Rows.Count} shown · {records.Count} media files · {records.Count(r => r.Issues.Count > 0)} to review";
    public string SelectionSummary => $"{Selection.Selected.Count} selected · Backups {(CreateBackup ? "on" : "off")}";
    public string Log { get; private set; } = "No folder loaded.";
    public bool IsScanning => cancellation is not null;
    public bool IsApplying => applying;
    public bool CanScan => !IsScanning && !IsApplying;
    public bool CanReviewChanges => rootPath is not null && !IsScanning && !IsApplying && Selection.Selected.Count > 0;
    public double Completed { get; private set; }
    public double Total { get; private set; } = 1;
    public string ProgressText { get; private set; } = "";
    public event PropertyChangedEventHandler? PropertyChanged;

    private void Notify() => PropertyChanged?.Invoke(this, new(null));
    public void ReportError(string message) { Status = message; Notify(); }

    public async Task ScanAsync(string root)
    {
        if (IsScanning || IsApplying) return;
        using var source = new CancellationTokenSource();
        cancellation = source;
        int current = ++generation;
        Status = $"Scanning {root}"; ProgressText = "Discovering files…"; Completed = 0; Total = 1; Notify();
        try
        {
            if (!Directory.Exists(root)) throw new DirectoryNotFoundException("The selected folder is no longer available.");
            var scanned = await scanner.ScanAsync(root, p => dispatch(() =>
            {
                if (current != generation || !IsScanning) return;
                Completed = p.Completed; Total = Math.Max(1, p.Total);
                ProgressText = $"{p.Completed} / {p.Total}"; Notify();
            }), source.Token);
            if (!source.IsCancellationRequested || scanned.Count > 0)
            {
                records = scanned;
                rootPath = Path.GetFullPath(root);
                Refresh();
                await LoadLogAsync();
                Status = source.IsCancellationRequested ? $"Partial results: {root}" : root;
            }
            else Status = "Scan stopped. Previous results kept.";
            ProgressText = source.IsCancellationRequested ? "Scan stopped" : "Scan complete";
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or ArgumentException)
        { Status = $"Scan failed: {ex.Message}"; }
        finally { cancellation = null; Notify(); }
    }

    public void Stop() { cancellation?.Cancel(); if (IsScanning) { Status = "Stopping scan…"; Notify(); } }

    public void Refresh(bool clearSelection = true)
    {
        if (clearSelection) Selection.Clear();
        var visible = LibraryQuery.Filter(records, Search, Media, View == "Review", View == "Review" ? Issue : "All review items");
        if (SortColumn is { } column) visible = Descending ? visible.OrderByDescending(r => LibraryQuery.SortValue(r, column)) : visible.OrderBy(r => LibraryQuery.SortValue(r, column));
        Rows.Clear();
        foreach (var record in visible) Rows.Add(new(record) { IsSelected = Selection.Selected.Contains(record.Path) });
        Notify();
    }

    public void Sort(string column) { Descending = SortColumn == column && !Descending; SortColumn = column; Refresh(false); }
    public void Click(MediaRow row, bool ctrl, bool shift, bool checkbox) { Selection.Click(Rows.Select(r => r.Record.Path).ToArray(), row.Record.Path, ctrl, shift, checkbox); SyncSelection(); }
    public void SelectAll() { Selection.SelectAll(Rows.Select(r => r.Record.Path).ToArray()); SyncSelection(); }
    public void ClearSelection() { Selection.Clear(); SyncSelection(); }

    public void SetRepairMethod(string id)
    {
        _ = RepairPlanner.FindMethod(id);
        SelectedRepairMethodId = id;
        Notify();
    }

    public void SetCreateBackup(bool enabled)
    {
        CreateBackup = enabled;
        Notify();
    }

    public RepairPreview BuildRepairPreview()
    {
        if (rootPath is null) throw new InvalidOperationException("Choose and scan a folder first.");
        RepairMethod method = RepairPlanner.FindMethod(SelectedRepairMethodId);
        var selected = records.Where(record => Selection.Selected.Contains(record.Path)).ToArray();
        if (selected.Length == 0) throw new InvalidOperationException("Select at least one file first.");
        return RepairPlanner.Preview(selected, method);
    }

    public async Task<IReadOnlyList<RepairExecutionResult>> ApplyRepairAsync(RepairPreview preview)
    {
        if (rootPath is null) throw new InvalidOperationException("Choose and scan a folder first.");
        if (IsScanning || IsApplying) throw new InvalidOperationException("Finish the current operation first.");
        if (preview.ApplicableCount == 0) return [];

        // Freeze the safety choice associated with the confirmation that just
        // occurred. Async execution must not observe a later UI toggle change.
        bool createBackup = CreateBackup;
        applying = true;
        Status = $"Applying {preview.ApplicableCount} repair{(preview.ApplicableCount == 1 ? "" : "s")}…";
        Notify();
        try
        {
            var service = new RepairService(rootPath);
            IReadOnlyList<RepairExecutionResult> results = await Task.Run(() => service.ApplyBatch(preview, createBackup));
            var replacements = results
                .Where(result => result.Success && result.RefreshedRecord is not null)
                .ToDictionary(result => result.Plan.Path, result => result.RefreshedRecord!, StringComparer.OrdinalIgnoreCase);
            records = records.Select(record => replacements.TryGetValue(record.Path, out var replacement) ? replacement : record).ToArray();
            Selection.Clear();
            Refresh(false);
            await LoadLogAsync();
            int succeeded = results.Count(result => result.Success);
            int failed = results.Count - succeeded;
            Status = failed == 0
                ? $"Applied {succeeded} repair{(succeeded == 1 ? "" : "s")}."
                : $"Applied {succeeded}; {failed} failed. See Repair log for details.";
            return results;
        }
        finally
        {
            applying = false;
            Notify();
        }
    }

    private async Task LoadLogAsync()
    {
        if (rootPath is null) { Log = "No folder loaded."; return; }
        string path = Path.Combine(rootPath, ".photo-repair-repair-log.csv");
        try { Log = File.Exists(path) ? await File.ReadAllTextAsync(path) : "No repairs have been recorded for this folder."; }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException) { Log = $"Could not read repair log: {ex.Message}"; }
    }

    private void SyncSelection()
    {
        foreach (var row in Rows) row.IsSelected = Selection.Selected.Contains(row.Record.Path);
        Notify();
    }
}
