# Microsoft Store product identity

The Microsoft Store product reservation for **Photo Metadata Repair Inspector** has been completed.

Use these exact values in the packaged Windows application manifest and Store build configuration:

```text
Package/Identity/Name: QortxAI.PhotoMetadataRepairInspector
Package/Identity/Publisher: CN=7F9981DB-6481-4EE5-8747-A3A63C186D7D
Package/Properties/PublisherDisplayName: QortxAI
Package Family Name (PFN): QortxAI.PhotoMetadataRepairInspector_whp60drgnydpm
Store ID: 9PPP5290T27G
```

Store product URL:

```text
https://apps.microsoft.com/detail/9PPP5290T27G
```

The MSA app ID shown in Partner Center is:

```text
1d745afc-c35e-4cb3-8c5f-eaf025ac8d47
```

Do not use the MSA app ID unless a feature actually requires Microsoft account authentication or related identity integration.

## Packaging rule

For Store builds, do not invent or regenerate package identity values. The MSIX manifest must use the Partner Center identity above. If Visual Studio's Store association tooling is used, verify that the generated manifest resolves to these exact values.

The initial native Windows implementation should remain a packaged WinUI 3 application under `windows-native/`, with Store packaging completed after read-only and repair parity are stable.
