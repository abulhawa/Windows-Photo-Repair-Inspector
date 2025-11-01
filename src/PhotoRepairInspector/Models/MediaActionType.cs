namespace PhotoRepairInspector.Models;

public enum MediaActionType
{
    NoChange,
    FixDateFromFilename,
    DeleteSmallerCompressedCopy,
    WriteExifFromFilename,
    MarkSuspicious
}
