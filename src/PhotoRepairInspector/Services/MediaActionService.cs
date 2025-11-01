using System;
using System.Globalization;
using System.IO;
using System.Windows.Media.Imaging;
using PhotoRepairInspector.Models;

namespace PhotoRepairInspector.Services;

public sealed class MediaActionService
{
    private readonly AppConfig _config;
    private readonly ActionLogger _logger;
    private readonly string _rootFolder;

    public MediaActionService(AppConfig config, ActionLogger logger, string rootFolder)
    {
        _config = config;
        _logger = logger;
        _rootFolder = rootFolder;
    }

    public void Apply(MediaFileInfo item)
    {
        switch (item.ProposedAction)
        {
            case MediaActionType.NoChange:
                return;
            case MediaActionType.FixDateFromFilename:
                ApplyFileDateFix(item);
                break;
            case MediaActionType.DeleteSmallerCompressedCopy:
                DeleteCompressedCopy(item);
                break;
            case MediaActionType.WriteExifFromFilename:
                WriteExifDate(item);
                break;
            case MediaActionType.MarkSuspicious:
                _logger.Log($"Mark suspicious	{item.FilePath}");
                break;
        }
    }

    private void ApplyFileDateFix(MediaFileInfo item)
    {
        if (item.ParsedDate is null)
        {
            return;
        }

        var newDate = item.ParsedDate.Value;
        File.SetCreationTime(item.FilePath, newDate);
        File.SetLastWriteTime(item.FilePath, newDate);
        _logger.Log($"FixDate	{item.FilePath}	{item.Created:o}	{newDate:o}");
    }

    private void DeleteCompressedCopy(MediaFileInfo item)
    {
        if (_config.MoveInsteadOfDelete)
        {
            var recycleRoot = Path.Combine(_rootFolder, _config.RecycleFolderName);
            string relative;
            try
            {
                relative = Path.GetRelativePath(_rootFolder, item.FilePath);
            }
            catch
            {
                relative = Path.GetFileName(item.FilePath);
            }

            if (relative.StartsWith("..", StringComparison.Ordinal))
            {
                relative = Path.GetFileName(item.FilePath);
            }

            var targetPath = Path.Combine(recycleRoot, relative);
            var targetDirectory = Path.GetDirectoryName(targetPath)!;
            Directory.CreateDirectory(targetDirectory);

            var baseName = Path.GetFileNameWithoutExtension(targetPath);
            var extension = Path.GetExtension(targetPath);
            var counter = 1;
            while (File.Exists(targetPath))
            {
                targetPath = Path.Combine(targetDirectory, $"{baseName}_{counter}{extension}");
                counter++;
            }

            File.Move(item.FilePath, targetPath);
            _logger.Log($"MoveDelete	{item.FilePath}	{targetPath}");
        }
        else
        {
            File.Delete(item.FilePath);
            _logger.Log($"Delete	{item.FilePath}");
        }
    }

    private void WriteExifDate(MediaFileInfo item)
    {
        if (item.ParsedDate is null)
        {
            return;
        }

        if (!string.Equals(item.Extension, ".jpg", StringComparison.OrdinalIgnoreCase) &&
            !string.Equals(item.Extension, ".jpeg", StringComparison.OrdinalIgnoreCase))
        {
            _logger.Log($"SkipWriteExif	{item.FilePath}	Unsupported format");
            return;
        }

        string? tempFile = null;
        try
        {
            tempFile = Path.GetTempFileName();
            using (var stream = File.Open(item.FilePath, FileMode.Open, FileAccess.Read))
            {
                var decoder = BitmapDecoder.Create(stream, BitmapCreateOptions.PreservePixelFormat, BitmapCacheOption.OnLoad);
                var frame = decoder.Frames[0];
                if (frame.Metadata is not BitmapMetadata metadata)
                {
                    _logger.Log($"SkipWriteExif	{item.FilePath}	No metadata");
                    return;
                }

                metadata = metadata.Clone();
                var exifValue = item.ParsedDate.Value.ToString("yyyy:MM:dd HH:mm:ss", CultureInfo.InvariantCulture);
                metadata.SetQuery("/app1/ifd/exif/{ushort=36867}", exifValue);
                metadata.SetQuery("/app1/ifd/exif/{ushort=36868}", exifValue);

                BitmapEncoder encoder = new JpegBitmapEncoder();
                encoder.Frames.Add(BitmapFrame.Create(frame, frame.Thumbnail, metadata, frame.ColorContexts));
                using var temp = File.Create(tempFile);
                encoder.Save(temp);
            }

            var backupPath = item.FilePath + ".bak";
            if (!File.Exists(backupPath))
            {
                File.Copy(item.FilePath, backupPath);
            }

            File.Copy(tempFile, item.FilePath, overwrite: true);
            _logger.Log($"WriteExif	{item.FilePath}	{item.ParsedDate:O}");
        }
        catch (Exception ex)
        {
            _logger.Log($"ErrorWriteExif	{item.FilePath}	{ex.Message}");
        }
        finally
        {
            if (tempFile != null && File.Exists(tempFile))
            {
                File.Delete(tempFile);
            }
        }
    }
}
