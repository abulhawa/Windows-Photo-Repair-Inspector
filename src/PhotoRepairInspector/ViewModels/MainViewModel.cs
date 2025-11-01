using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.IO;
using System.Linq;
using System.Text;
using System.Windows.Data;
using System.Windows.Input;
using PhotoRepairInspector.Models;
using PhotoRepairInspector.Services;

namespace PhotoRepairInspector.ViewModels;

public sealed class MainViewModel : INotifyPropertyChanged, IDisposable
{
    private readonly MediaScanner _scanner = new();
    private readonly ObservableCollection<MediaFileViewModel> _items = new();
    private readonly ObservableCollection<MediaGroupInfo> _suspiciousGroups = new();
    private readonly StringBuilder _logBuilder = new();
    private readonly RelayCommand _scanFolderCommand;
    private readonly RelayCommand _applySelectedCommand;
    private readonly RelayCommand _applySingleCommand;
    private readonly RelayCommand _ignoreSingleCommand;
    private ActionLogger? _logger;
    private MediaActionService? _actionService;
    private string? _currentRoot;
    private bool _showOnlyWithChanges;
    private MediaFileViewModel? _selectedItem;
    private MediaGroupInfo? _selectedGroup;
    private int _selectedTabIndex;

    public MainViewModel()
    {
        Configuration = new AppConfig();
        ActionChoices = new List<ActionChoice>
        {
            new(MediaActionType.NoChange, "No change"),
            new(MediaActionType.FixDateFromFilename, "Fix date from filename"),
            new(MediaActionType.DeleteSmallerCompressedCopy, "Delete smaller compressed copy"),
            new(MediaActionType.WriteExifFromFilename, "Keep but write EXIF date"),
            new(MediaActionType.MarkSuspicious, "Mark as suspicious (missing original)")
        };

        FilteredItems = CollectionViewSource.GetDefaultView(_items);
        FilteredItems.Filter = FilterItems;

        SuspiciousGroups = new ReadOnlyObservableCollection<MediaGroupInfo>(_suspiciousGroups);

        _scanFolderCommand = new RelayCommand(_ => ScanFolder());
        _applySelectedCommand = new RelayCommand(_ => ApplySelectedChanges(), _ => _items.Any(i => i.SelectedActionType != MediaActionType.NoChange));
        _applySingleCommand = new RelayCommand(item => ApplySingle(item as MediaFileViewModel), item => item is MediaFileViewModel vm && vm.SelectedActionType != MediaActionType.NoChange);
        _ignoreSingleCommand = new RelayCommand(item => (item as MediaFileViewModel)?.ResetSelection());

        ScanFolderCommand = _scanFolderCommand;
        ApplySelectedCommand = _applySelectedCommand;
        ApplySingleCommand = _applySingleCommand;
        IgnoreSingleCommand = _ignoreSingleCommand;
    }

    public event PropertyChangedEventHandler? PropertyChanged;

    public AppConfig Configuration { get; }

    public ICollectionView FilteredItems { get; }

    public IReadOnlyList<ActionChoice> ActionChoices { get; }

    public ReadOnlyObservableCollection<MediaGroupInfo> SuspiciousGroups { get; }

    public IEnumerable<MediaFileViewModel> Items => _items;

    public ICommand ScanFolderCommand { get; }
    public ICommand ApplySelectedCommand { get; }
    public ICommand ApplySingleCommand { get; }
    public ICommand IgnoreSingleCommand { get; }

    public bool ShowOnlyWithChanges
    {
        get => _showOnlyWithChanges;
        set
        {
            if (_showOnlyWithChanges != value)
            {
                _showOnlyWithChanges = value;
                FilteredItems.Refresh();
                OnPropertyChanged(nameof(ShowOnlyWithChanges));
            }
        }
    }

    public MediaFileViewModel? SelectedItem
    {
        get => _selectedItem;
        set
        {
            if (_selectedItem != value)
            {
                _selectedItem = value;
                OnPropertyChanged(nameof(SelectedItem));
                _applySingleCommand.RaiseCanExecuteChanged();
            }
        }
    }

    public MediaGroupInfo? SelectedGroup
    {
        get => _selectedGroup;
        set
        {
            if (_selectedGroup != value)
            {
                _selectedGroup = value;
                OnPropertyChanged(nameof(SelectedGroup));
                if (_selectedGroup != null)
                {
                    var first = _items.FirstOrDefault(i => i.GroupKey == _selectedGroup.GroupKey);
                    if (first != null)
                    {
                        SelectedItem = first;
                    }
                }
            }
        }
    }

    public string LogText => _logBuilder.ToString();

    public int SelectedTabIndex
    {
        get => _selectedTabIndex;
        set
        {
            if (_selectedTabIndex != value)
            {
                _selectedTabIndex = value;
                OnPropertyChanged(nameof(SelectedTabIndex));
            }
        }
    }

    private void ScanFolder()
    {
        using var dialog = new System.Windows.Forms.FolderBrowserDialog
        {
            Description = "Select the root folder to scan"
        };

        if (dialog.ShowDialog() != System.Windows.Forms.DialogResult.OK)
        {
            return;
        }

        _currentRoot = dialog.SelectedPath;
        _logger?.Dispose();
        var logPath = Path.Combine(_currentRoot, $"{Configuration.LogFileNamePrefix}-{DateTime.Now:yyyyMMddHHmmss}.txt");
        _logger = new ActionLogger(logPath);
        _actionService = new MediaActionService(Configuration, _logger, _currentRoot);

        AppendLog($"Scanning {_currentRoot}...");
        var mediaItems = _scanner.Scan(_currentRoot, Configuration, progress => AppendLog($"Found {progress}"));

        foreach (var existing in _items.ToList())
        {
            existing.PropertyChanged -= OnItemPropertyChanged;
        }

        _items.Clear();
        foreach (var info in mediaItems)
        {
            var vm = new MediaFileViewModel(info);
            vm.PropertyChanged += OnItemPropertyChanged;
            _items.Add(vm);
        }

        BuildSuspiciousGroups(mediaItems);
        FilteredItems.Refresh();
        AppendLog($"Scan complete: {mediaItems.Count} items");
        _applySelectedCommand.RaiseCanExecuteChanged();
        _applySingleCommand.RaiseCanExecuteChanged();
    }

    private void BuildSuspiciousGroups(IReadOnlyList<MediaFileInfo> items)
    {
        _suspiciousGroups.Clear();
        var groups = items
            .Where(i => !string.IsNullOrEmpty(i.GroupKey))
            .GroupBy(i => i.GroupKey)
            .Select(g => new MediaGroupInfo
            {
                GroupKey = g.Key,
                Items = g.ToList()
            })
            .Where(g => g.OnlyCompressed || g.AllWhatsApp);

        foreach (var group in groups)
        {
            _suspiciousGroups.Add(group);
        }

        OnPropertyChanged(nameof(SuspiciousGroups));
    }

    private void ApplySelectedChanges()
    {
        if (_actionService == null)
        {
            return;
        }

        foreach (var item in _items.Where(i => i.SelectedActionType != MediaActionType.NoChange).ToList())
        {
            ApplyAndRefresh(item);
        }

        AppendLog("Apply completed");
        FilteredItems.Refresh();
    }

    private void ApplySingle(MediaFileViewModel? item)
    {
        if (item == null || _actionService == null)
        {
            return;
        }

        ApplyAndRefresh(item);
        AppendLog($"Applied action for {item.FileName}");
        FilteredItems.Refresh();
    }

    private void ApplyAndRefresh(MediaFileViewModel item)
    {
        if (_actionService == null)
        {
            return;
        }

        try
        {
            item.ApplySelection();
            _actionService.Apply(item.Info);
            item.RefreshFromFileSystem();
            item.MarkApplied();
            item.ResetSelection();
        }
        catch (Exception ex)
        {
            AppendLog($"Error applying action to {item.FileName}: {ex.Message}");
        }
        finally
        {
            _applySelectedCommand.RaiseCanExecuteChanged();
            _applySingleCommand.RaiseCanExecuteChanged();
            if (ShowOnlyWithChanges)
            {
                FilteredItems.Refresh();
            }
        }
    }

    private bool FilterItems(object obj)
    {
        if (obj is not MediaFileViewModel item)
        {
            return false;
        }

        if (!ShowOnlyWithChanges)
        {
            return true;
        }

        return item.SelectedActionType != MediaActionType.NoChange || item.SuggestedActionType != MediaActionType.NoChange;
    }

    private void AppendLog(string message)
    {
        _logBuilder.AppendLine(message);
        OnPropertyChanged(nameof(LogText));
    }

    private void OnItemPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(MediaFileViewModel.SelectedActionType) ||
            e.PropertyName == nameof(MediaFileViewModel.SuggestedActionType))
        {
            _applySelectedCommand.RaiseCanExecuteChanged();
            _applySingleCommand.RaiseCanExecuteChanged();
            if (ShowOnlyWithChanges)
            {
                FilteredItems.Refresh();
            }
        }
    }

    public void Dispose()
    {
        _logger?.Dispose();
    }

    private void OnPropertyChanged(string propertyName)
        => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));

    public readonly record struct ActionChoice(MediaActionType Action, string Description);
}
