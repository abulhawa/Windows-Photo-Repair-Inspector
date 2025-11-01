using System;
using System.Collections.Generic;

namespace PhotoRepairInspector.Models;

public class AppConfig
{
    public DateTime ProblemDate { get; set; } = new(2025, 10, 26);
    public int ProblemDateToleranceDays { get; set; } = 1;
    public bool AutoGroupByParsedDate { get; set; } = true;
    public double MinCompressedSizeRatio { get; set; } = 0.7;
    public bool MoveInsteadOfDelete { get; set; } = true;
    public string RecycleFolderName { get; set; } = "Recovered_Deleted";
    public IReadOnlyCollection<string> SupportedExtensions { get; set; } = new[]
    {
        ".jpg", ".jpeg", ".png", ".heic", ".mp4", ".mov"
    };
    public string LogFileNamePrefix { get; set; } = "photo-fixer-log";
}
