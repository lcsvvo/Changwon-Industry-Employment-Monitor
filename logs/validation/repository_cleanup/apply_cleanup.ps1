$ErrorActionPreference = 'Stop'
$cleanupRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$cleanupPrefix = $cleanupRoot.TrimEnd('\') + '\'
$plan = Import-Csv -LiteralPath (Join-Path $PSScriptRoot 'inventory.csv')
$validation = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'dependency_validation.json') -Raw | ConvertFrom-Json
if ($validation.unresolved.Count -ne 0) { throw 'Unresolved retained dependency; cleanup prohibited' }
if (($plan | Where-Object { $_.category -eq 'DELETE_LOW_VALUE' -and $_.tracked -eq 'True' }).Count -ne 0) { throw 'Tracked deletion requires further review' }
$operations = @()
foreach ($row in $plan) {
    if ($row.category -eq 'KEEP_FINAL') { continue }
    $source = [IO.Path]::GetFullPath((Join-Path $cleanupRoot $row.path))
    if (-not $source.StartsWith($cleanupPrefix, [StringComparison]::OrdinalIgnoreCase)) { throw "Outside workspace: $source" }
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Missing: $source" }
    if ($row.category -eq 'ARCHIVE_EXPERIMENT') {
        $target = [IO.Path]::GetFullPath((Join-Path $cleanupRoot $row.target))
        if (-not $target.StartsWith($cleanupPrefix, [StringComparison]::OrdinalIgnoreCase)) { throw "Outside workspace: $target" }
        if (Test-Path -LiteralPath $target) { throw "Collision: $target" }
        New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($target)) -Force | Out-Null
        if ($row.tracked -eq 'True') {
            & git -C $cleanupRoot mv -- $row.path $row.target
            if ($LASTEXITCODE -ne 0) { throw "git mv failed: $source" }
        } else { Move-Item -LiteralPath $source -Destination $target }
    } elseif ($row.category -eq 'DELETE_LOW_VALUE') { Remove-Item -LiteralPath $source }
    else { throw "Unsupported category: $($row.category)" }
    $operations += [pscustomobject]@{path=$row.path;category=$row.category;target=$row.target}
}
$operations | Export-Csv -LiteralPath (Join-Path $PSScriptRoot 'operations.csv') -NoTypeInformation -Encoding UTF8
$operations | Group-Object category | Select-Object Name,Count | Format-Table
