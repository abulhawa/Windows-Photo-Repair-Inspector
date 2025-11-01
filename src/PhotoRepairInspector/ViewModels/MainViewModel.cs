using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using System.Windows.Input;
using PhotoRepairInspector.Models;
using PhotoRepairInspector.Services;

namespace PhotoRepairInspector.ViewModels;

public sealed class MainViewModel : INotifyPropertyChanged, IDisposable
{
    private readonly MediaScanner _scanner = new();
    private readonly ObservableCollection<MediaFileViewModel> _items = new();
    private readonly StringBuilder _logBuilder = new();
    private readonly RelayCommand _scanFolderCommand;
    private readonly RelayCommand _applyFixesCommand;

    private ActionLogger? _logger;
    private MediaActionService? _actionService;
    private string? _currentRoot;
    private bool _isScanning;
    private int _totalItems;
    private int _pendingFixCount;

    public MainViewModel()
    {
        Configuration = new AppConfig();
        _scanFolderCommand = new RelayCommand(_ => ScanFolder(), _ => !IsScanning);
        _applyFixesCommand = new RelayCommand(_ => ApplyFixes(), _ => PendingFixCount > 0 && !IsScanning);

        ScanFolderCommand = _scanFolderCommand;
        ApplyFixesCommand = _applyFixesCommand;
    }

    public event PropertyChangedEventHandler? PropertyChanged;

    public AppConfig Configuration { get; }

    public IEnumerable<MediaFileViewModel> Items => _items;

    public ICommand ScanFolderCommand { get; }
    public ICommand ApplyFixesCommand { get; }

    public bool IsScanning
    {
        get => _isScanning;
        private set
        {
            if (_isScanning != value)
            {
                _isScanning = value;
                OnPropertyChanged(nameof(IsScanning));
                _scanFolderCommand.RaiseCanExecuteChanged();
                _applyFixesCommand.RaiseCanExecuteChanged();
            }
        }
    }

    public string LogText => _logBuilder.ToString();

    public int TotalItems
    {
        get => _totalItems;
        private set
        {
            if (_totalItems != value)
            {
                _totalItems = value;
                OnPropertyChanged(nameof(TotalItems));
            }
        }
    }

    public int PendingFixCount
    {
        get => _pendingFixCount;
        private set
        {
            if (_pendingFixCount != value)
            {
                _pendingFixCount = value;
                OnPropertyChanged(nameof(PendingFixCount));
                _applyFixesCommand.RaiseCanExecuteChanged();
            }
        }
    }

    private async void ScanFolder()
    {
        if (IsScanning)
        {
            return;
        }

        using var dialog = new FolderBrowserDialog
        {
            Description = "Select the root folder to scan"
        };

        if (dialog.ShowDialog() != DialogResult.OK)
        {
            return;
        }

        _currentRoot = dialog.SelectedPath;
        _logger?.Dispose();

        IReadOnlyList<MediaFileInfo> mediaItems = Array.Empty<MediaFileInfo>();
        var progressCount = 0;

        try
        {
            IsScanning = true;

            var logPath = Path.Combine(_currentRoot, $"{Configuration.LogFileNamePrefix}-{DateTime.Now:yyyyMMddHHmmss}.txt");
            _logger = new ActionLogger(logPath);
            _actionService = new MediaActionService(Configuration, _logger, _currentRoot);

            _logBuilder.Clear();
            AppendLog($"Scanning {_currentRoot}...");

            mediaItems = await Task.Run(() =>
                _scanner.Scan(_currentRoot, Configuration, progress =>
                {
                    var current = Interlocked.Increment(ref progressCount);
                    ReportProgress(current, progress);
                }));
        }
        catch (Exception ex)
        {
            AppendLog($"Scan failed: {ex.Message}");
            return;
        }
        finally
        {
            IsScanning = false;
        }

        foreach (var item in _items.ToList())
        {
            item.PropertyChanged -= OnItemPropertyChanged;
        }

        _items.Clear();

        var fixable = mediaItems
            .Where(i => i.ProposedAction == MediaActionType.FixDateFromFilename)
            .OrderBy(i => i.ParsedDate ?? DateTime.MaxValue)
            .ThenBy(i => i.FileName)
            .ToList();

        foreach (var info in fixable)
        {
            var vm = new MediaFileViewModel(info);
            vm.PropertyChanged += OnItemPropertyChanged;
            _items.Add(vm);
        }

        UpdateCounts();

        AppendLog($"Scan complete: {mediaItems.Count} files scanned, {fixable.Count} need date fixes.");
    }

    private void ApplyFixes()
    {
        if (_actionService == null || PendingFixCount == 0)
        {
            return;
        }

        var itemsToFix = _items.Where(i => i.HasPendingChanges).ToList();
        AppendLog($"Applying date fixes to {itemsToFix.Count} files...");

        foreach (var item in itemsToFix)
        {
            try
            {
                item.PrepareForApply();
                _actionService.Apply(item.Info);
                item.RefreshFromFileSystem();
                item.MarkApplied();
            }
            catch (Exception ex)
            {
                AppendLog($"Error fixing {item.FileName}: {ex.Message}");
            }
        }

        UpdateCounts();
        AppendLog("Date fix run complete.");
    }

    private void UpdateCounts()
    {
        TotalItems = _items.Count;
        PendingFixCount = _items.Count(i => i.HasPendingChanges);
        OnPropertyChanged(nameof(Items));
    }

    private void ReportProgress(int count, string filePath)
    {
        if (count == 1 || count % 50 == 0)
        {
            var name = Path.GetFileName(filePath);
            var message = string.IsNullOrEmpty(name)
                ? $"Scanning... {count} files processed"
                : $"Scanning... {count} files processed (last: {name})";
            AppendLog(message);
        }
    }

    private void AppendLog(string message)
    {
        var dispatcher = System.Windows.Application.Current?.Dispatcher;
        if (dispatcher == null || dispatcher.CheckAccess())
        {
            _logBuilder.AppendLine(message);
            OnPropertyChanged(nameof(LogText));
        }
        else
        {
            dispatcher.Invoke(() =>
            {
                _logBuilder.AppendLine(message);
                OnPropertyChanged(nameof(LogText));
            });
        }
    }

    private void OnItemPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(MediaFileViewModel.IsSelected) ||
            e.PropertyName == nameof(MediaFileViewModel.HasPendingChanges))
        {
            UpdateCounts();
        }
    }

    public void Dispose()
    {
        _logger?.Dispose();
    }

    private void OnPropertyChanged(string propertyName)
        => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
}
