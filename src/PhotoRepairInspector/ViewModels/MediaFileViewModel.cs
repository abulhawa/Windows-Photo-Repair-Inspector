using System;
using System.ComponentModel;
using System.IO;
using System.Runtime.CompilerServices;
using PhotoRepairInspector.Models;

namespace PhotoRepairInspector.ViewModels;

public class MediaFileViewModel : INotifyPropertyChanged
{
    private readonly MediaFileInfo _info;
    private bool _isSelected;

    public MediaFileViewModel(MediaFileInfo info)
    {
        _info = info;
        _isSelected = info.ProposedAction == MediaActionType.FixDateFromFilename;
    }

    public MediaFileInfo Info => _info;

    public event PropertyChangedEventHandler? PropertyChanged;

    public string FileName => _info.FileName;
    public string DirectoryName => _info.DirectoryName;
    public string FullPath => _info.FilePath;
    public string ParsedDateDisplay => _info.ParsedDate?.ToString("yyyy-MM-dd HH:mm:ss") ?? "n/a";
    public string CreatedDisplay => _info.Created.ToString("yyyy-MM-dd HH:mm:ss");
    public string ModifiedDisplay => _info.Modified.ToString("yyyy-MM-dd HH:mm:ss");
    public string ProposedDateDisplay => _info.ParsedDate?.ToString("yyyy-MM-dd HH:mm:ss") ?? "n/a";
    public string Reason => _info.ActionReason ?? string.Empty;
    public string Notes => _info.Notes ?? string.Empty;

    public bool CanFix => _info.ProposedAction == MediaActionType.FixDateFromFilename;

    public bool IsSelected
    {
        get => _isSelected;
        set
        {
            if (_isSelected != value)
            {
                _isSelected = value;
                OnPropertyChanged();
                OnPropertyChanged(nameof(HasPendingChanges));
            }
        }
    }

    public bool HasPendingChanges => CanFix && IsSelected;

    public void PrepareForApply()
    {
        _info.ProposedAction = HasPendingChanges ? MediaActionType.FixDateFromFilename : MediaActionType.NoChange;
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

    public void MarkApplied()
    {
        _isSelected = false;
        _info.ProposedAction = MediaActionType.NoChange;
        OnPropertyChanged(nameof(IsSelected));
        OnPropertyChanged(nameof(HasPendingChanges));
    }

    private void OnPropertyChanged([CallerMemberName] string? propertyName = null)
        => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
}
