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
    public ObservableCollection<MediaRow> Rows { get; } = [];
    public SelectionModel Selection { get; } = new();
    public string Search { get; set; } = "";
    public string Media { get; set; } = "All";
    public string Issue { get; set; } = "All review items";
    public string View { get; set; } = "Library";
    public string? SortColumn { get; private set; }
    public bool Descending { get; private set; }
    public string Status { get; private set; } = "Choose a folder to inspect";
    public string Summary => $"{Rows.Count} shown · {records.Count} media files · {records.Count(r => r.Issues.Count > 0)} to review";
    public string SelectionSummary => $"{Selection.Selected.Count} selected · Read-only edition";
    public string Log { get; private set; } = "No folder loaded. Repairs are not available in this edition.";
    public bool IsScanning => cancellation is not null;
    public bool CanScan => !IsScanning;
    public double Completed { get; private set; }
    public double Total { get; private set; } = 1;
    public string ProgressText { get; private set; } = "";
    public event PropertyChangedEventHandler? PropertyChanged;
    private void Notify() => PropertyChanged?.Invoke(this, new(null));
    public void ReportError(string message) { Status = message; Notify(); }

    public async Task ScanAsync(string root)
    {
        if (IsScanning) return;
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
                Refresh();
                string logPath = Path.Combine(root, ".photo-repair-repair-log.csv");
                try { Log = File.Exists(logPath) ? await File.ReadAllTextAsync(logPath) : "No repairs have been recorded for this folder."; }
                catch (Exception ex) when (ex is IOException or UnauthorizedAccessException) { Log = $"Could not read repair log: {ex.Message}"; }
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
    private void SyncSelection() { foreach (var row in Rows) row.IsSelected = Selection.Selected.Contains(row.Record.Path); Notify(); }
}
