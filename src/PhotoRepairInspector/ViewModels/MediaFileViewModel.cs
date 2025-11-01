using System;
using System.ComponentModel;
using System.IO;
using System.Linq;
using System.Runtime.CompilerServices;
using System.Windows.Media.Imaging;
using PhotoRepairInspector.Models;
using PhotoRepairInspector.Utilities;

namespace PhotoRepairInspector.ViewModels;

public class MediaFileViewModel : INotifyPropertyChanged
{
    private readonly MediaFileInfo _info;
    private BitmapImage? _thumbnail;
    private BitmapImage? _previewImage;
    private MediaActionType _selectedActionType;
    private MediaActionType _suggestedActionType;

    public MediaFileViewModel(MediaFileInfo info)
    {
        _info = info;
        _suggestedActionType = info.ProposedAction;
        _selectedActionType = info.ProposedAction == MediaActionType.DeleteSmallerCompressedCopy
            ? MediaActionType.NoChange
            : info.ProposedAction;
    }

    public MediaFileInfo Info => _info;

    public event PropertyChangedEventHandler? PropertyChanged;

    public string FileName => _info.FileName;
    public string DirectoryName => _info.DirectoryName;
    public string FullPath => _info.FilePath;
    public string ParsedDateDisplay => _info.ParsedDate?.ToString("yyyy-MM-dd HH:mm:ss") ?? "—";
    public string CreatedDisplay => _info.Created.ToString("yyyy-MM-dd HH:mm:ss");
    public string ModifiedDisplay => _info.Modified.ToString("yyyy-MM-dd HH:mm:ss");
    public string ProposedDateDisplay => _info.ParsedDate?.ToString("yyyy-MM-dd HH:mm:ss") ?? "—";
    public string SizeDisplay => _info.SizeDisplay;
    public string Source => _info.Source.ToString();
    public string GroupKey => _info.GroupKey;
    public string Notes => _info.Notes ?? string.Empty;
    public bool IsImage => _info.IsImage;
    public bool IsVideo => _info.IsVideo;
    public string? Resolution => _info.Resolution;
    public string ActionReason => _info.ActionReason ?? string.Empty;
    public string PlannedAction => DescribeAction(SelectedActionType);
    public string ExifStatus => _info.ExifDate?.ToString("yyyy-MM-dd HH:mm:ss") ?? "not present";
    public string DuplicateSummary => BuildDuplicateSummary();
    public bool HasPendingChanges => SelectedActionType != MediaActionType.NoChange;
    public MediaActionType SuggestedActionType
    {
        get => _suggestedActionType;
        private set
        {
            if (_suggestedActionType != value)
            {
                _suggestedActionType = value;
                OnPropertyChanged(nameof(SuggestedActionType));
            }
        }
    }

    public MediaActionType SelectedActionType
    {
        get => _selectedActionType;
        set
        {
            if (_selectedActionType != value)
            {
                _selectedActionType = value;
                OnPropertyChanged();
                OnPropertyChanged(nameof(HasPendingChanges));
                OnPropertyChanged(nameof(PlannedAction));
            }
        }
    }

    public BitmapImage? Thumbnail => _thumbnail ??= _info.IsImage ? ImagePreviewLoader.LoadThumbnail(_info.FilePath, 96) : null;

    public BitmapImage? PreviewImage => _previewImage ??= _info.IsImage ? ImagePreviewLoader.LoadThumbnail(_info.FilePath, 640) : null;

    public void ApplySelection()
    {
        _info.ProposedAction = SelectedActionType;
    }

    public void RefreshFromFileSystem()
    {
        if (!File.Exists(_info.FilePath))
        {
            return;
        }

        var fileInfo = new FileInfo(_info.FilePath);
        _info.Created = fileInfo.CreationTime;
        _info.Modified = fileInfo.LastWriteTime;
        OnPropertyChanged(nameof(CreatedDisplay));
        OnPropertyChanged(nameof(ModifiedDisplay));
    }

    public void ResetSelection()
    {
        SelectedActionType = MediaActionType.NoChange;
    }

    public void MarkApplied()
    {
        SuggestedActionType = MediaActionType.NoChange;
        _info.ProposedAction = MediaActionType.NoChange;
        OnPropertyChanged(nameof(PlannedAction));
        OnPropertyChanged(nameof(Notes));
    }

    private string BuildDuplicateSummary()
    {
        if (_info.Duplicates == null || _info.Duplicates.Count <= 1)
        {
            return "No duplicates detected";
        }

        var parts = _info.Duplicates
            .OrderByDescending(x => x.Size)
            .Select(x => $"{x.FileName} ({FileSizeFormatter.ToDisplay(x.Size)})");
        return "Duplicates in group: " + string.Join(", ", parts);
    }

    private static string DescribeAction(MediaActionType action)
        => action switch
        {
            MediaActionType.NoChange => "No change",
            MediaActionType.FixDateFromFilename => "Fix date from filename",
            MediaActionType.DeleteSmallerCompressedCopy => "Delete smaller compressed copy",
            MediaActionType.WriteExifFromFilename => "Keep but write EXIF date",
            MediaActionType.MarkSuspicious => "Mark as suspicious (missing original)",
            _ => "No change"
        };

    private void OnPropertyChanged([CallerMemberName] string? propertyName = null)
        => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
}
