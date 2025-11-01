using System;
using System.IO;
using System.Windows.Media.Imaging;

namespace PhotoRepairInspector.Utilities;

public static class ImagePreviewLoader
{
    public static BitmapImage? LoadThumbnail(string path, int decodePixelWidth = 256)
    {
        if (!File.Exists(path))
        {
            return null;
        }

        try
        {
            var image = new BitmapImage();
            image.BeginInit();
            image.CacheOption = BitmapCacheOption.OnLoad;
            image.UriSource = new Uri(path);
            image.DecodePixelWidth = decodePixelWidth;
            image.EndInit();
            image.Freeze();
            return image;
        }
        catch
        {
            return null;
        }
    }
}
