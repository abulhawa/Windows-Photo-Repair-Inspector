using Microsoft.UI.Input;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
using PhotoRepair.Core;
using PhotoRepair.Windows;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage.Pickers;
using Windows.System;
using Windows.UI.Core;

namespace PhotoRepair.App;

public sealed partial class MainWindow : Window
{
    private readonly InspectionViewModel model;
    private bool ready;
    public MainWindow()
    {
        model = new(action => DispatcherQueue.TryEnqueue(() => action()));
        InitializeComponent();
        Root.DataContext = model;
        AppWindow.Resize(new(1450, 820));
        Closed += (_, _) => model.Stop();
        ready = true;
        ReviewFilter.Visibility = Visibility.Collapsed;
    }
    private async void PickFolder(object sender, RoutedEventArgs e)
    {
        try
        {
            var picker = new FolderPicker(); picker.FileTypeFilter.Add("*");
            WinRT.Interop.InitializeWithWindow.Initialize(picker, WinRT.Interop.WindowNative.GetWindowHandle(this));
            var folder = await picker.PickSingleFolderAsync();
            if (folder is not null) await model.ScanAsync(folder.Path);
        }
        catch (Exception ex) { model.ReportError($"Could not open folder: {ex.Message}"); }
    }
    private void StopScan(object sender, RoutedEventArgs e) => model.Stop();
    private void SearchChanged(object sender, TextChangedEventArgs e) { if (ready) { model.Search = SearchBox.Text; model.Refresh(); } }
    private void FilterChanged(object sender, SelectionChangedEventArgs e)
    {
        if (!ready) return;
        model.Media = ((ComboBoxItem)MediaFilter.SelectedItem).Tag.ToString()!;
        model.Issue = ((ComboBoxItem)ReviewFilter.SelectedItem).Content.ToString()!;
        model.Refresh();
    }
    private void ViewChanged(object sender, SelectionChangedEventArgs e)
    {
        if (!ready) return;
        model.View = ((ComboBoxItem)ViewPicker.SelectedItem).Content.ToString()!;
        Table.Visibility = model.View == "Repair log" ? Visibility.Collapsed : Visibility.Visible;
        LogPanel.Visibility = model.View == "Repair log" ? Visibility.Visible : Visibility.Collapsed;
        ReviewFilter.Visibility = model.View == "Review" ? Visibility.Visible : Visibility.Collapsed;
        model.Refresh();
    }
    private void RepairMethodChanged(object sender, SelectionChangedEventArgs e)
    {
        if (!ready || RepairMethodPicker.SelectedItem is not ComboBoxItem item) return;
        model.SetRepairMethod(item.Tag.ToString()!);
    }
    private void BackupToggled(object sender, RoutedEventArgs e)
    {
        if (ready) model.SetCreateBackup(BackupToggle.IsOn);
    }
    private async void ReviewChanges(object sender, RoutedEventArgs e)
    {
        try
        {
            RepairPreview preview = model.BuildRepairPreview();
            string examples = string.Join("\n\n", preview.Examples.Select(item =>
                $"{item.Name}\n{item.Method.Label}\n{item.Before}  →  {item.After}"));
            string text = $"Selected: {preview.SelectedCount}\nApplicable: {preview.ApplicableCount}\nSkipped: {preview.SkippedCount}";
            if (!model.CreateBackup)
                text += "\n\nWARNING: Backups are OFF. These changes will be made in place without a recovery copy created by this application.";
            if (preview.SkippedCount > 0)
            {
                var reasons = preview.Items.Where(item => !item.Applicable)
                    .GroupBy(item => item.SkipReason)
                    .Select(group => $"{group.Count()} skipped: {group.Key}");
                text += "\n\n" + string.Join("\n", reasons);
            }
            if (examples.Length > 0)
                text += $"\n\nExamples (up to 10):\n\n{examples}";

            var dialog = new ContentDialog
            {
                XamlRoot = Root.XamlRoot,
                Title = "Review repair changes",
                Content = new ScrollViewer
                {
                    MaxHeight = 520,
                    Content = new TextBlock { Text = text, TextWrapping = TextWrapping.Wrap, IsTextSelectionEnabled = true }
                },
                CloseButtonText = preview.ApplicableCount > 0 ? "Cancel" : "Close",
                DefaultButton = ContentDialogButton.Primary
            };
            if (preview.ApplicableCount > 0) dialog.PrimaryButtonText = "Apply repairs";

            ContentDialogResult result = await dialog.ShowAsync();
            if (result == ContentDialogResult.Primary)
                await model.ApplyRepairAsync(preview);
        }
        catch (Exception ex)
        {
            model.ReportError($"Repair could not start: {ex.Message}");
        }
    }
    private void SortColumn(object sender, RoutedEventArgs e) => model.Sort(((Button)sender).Content.ToString()!);
    private void SelectAll(object sender, RoutedEventArgs e) => model.SelectAll();
    private void ClearSelection(object sender, RoutedEventArgs e) => model.ClearSelection();
    private static bool Down(VirtualKey key) => InputKeyboardSource.GetKeyStateForCurrentThread(key).HasFlag(CoreVirtualKeyStates.Down);
    private void SelectRow(object sender, bool checkbox)
    {
        if (sender is FrameworkElement { DataContext: MediaRow row }) model.Click(row, Down(VirtualKey.Control), Down(VirtualKey.Shift), checkbox);
    }
    private void CheckboxClicked(object sender, RoutedEventArgs e) => SelectRow(sender, true);
    private void RowTapped(object sender, TappedRoutedEventArgs e)
    {
        var element = e.OriginalSource as DependencyObject;
        while (element is not null && !ReferenceEquals(element, sender))
        {
            if (element is CheckBox) return;
            element = VisualTreeHelper.GetParent(element);
        }
        SelectRow(sender, false); e.Handled = true;
    }
    private void RowKeyDown(object sender, KeyRoutedEventArgs e)
    {
        if (e.Key == VirtualKey.Space && e.OriginalSource is not CheckBox) { SelectRow(sender, true); e.Handled = true; }
    }
    private async void OpenFile(object sender, RoutedEventArgs e)
    {
        if (sender is not FrameworkElement { DataContext: MediaRow row }) return;
        try { await Launcher.LaunchFileAsync(await global::Windows.Storage.StorageFile.GetFileFromPathAsync(row.Record.Path)); }
        catch (Exception ex) { model.ReportError(ex.Message); }
    }
    private async void RevealFile(object sender, RoutedEventArgs e)
    {
        if (sender is not FrameworkElement { DataContext: MediaRow row }) return;
        try
        {
            var folder = await global::Windows.Storage.StorageFolder.GetFolderFromPathAsync(row.Record.Location);
            var options = new FolderLauncherOptions();
            options.ItemsToSelect.Add(await global::Windows.Storage.StorageFile.GetFileFromPathAsync(row.Record.Path));
            await Launcher.LaunchFolderAsync(folder, options);
        }
        catch (Exception ex) { model.ReportError(ex.Message); }
    }
    private void CopyPath(object sender, RoutedEventArgs e)
    {
        if (sender is not FrameworkElement { DataContext: MediaRow row }) return;
        var data = new DataPackage(); data.SetText(row.Record.Path); Clipboard.SetContent(data);
    }
}
