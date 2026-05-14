# install.ps1 - PowerShell port of install.sh
#
# Downloads and installs the inngest CLI:
# - Checks for latest release
# - Downloads the correct artifact for your system
# - Verifies the SHA256 checksum
# - Extracts and installs the binary

#Requires -Version 5.1

$ErrorActionPreference = "Stop"

$binname = "inngest"
$reponame = "inngest"
$base = "https://github.com/inngest"

function Get-OSName {
    if (($IsWindows -eq $true) -or ($env:OS -eq "Windows_NT")) { return "windows" }
    if ($IsMacOS -eq $true) { return "darwin" }
    if (((Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue).Caption) -match "Windows") { return "windows" }
    return "linux"
}

function Get-ArchName {
    try {
        $arch = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture
        switch ($arch.ToString()) {
            "X64"   { return "amd64" }
            "Arm64" { return "arm64" }
            "X86"   { return "386" }
            default { return $arch.ToString().ToLower() }
        }
    }
    catch {
        if ([Environment]::Is64BitOperatingSystem) { return "amd64" }
        return "386"
    }
}

function Get-GitHubLatestVersion {
    param([string]$OwnerRepo)
    $apiUrl = "https://api.github.com/repos/$OwnerRepo/releases/latest"
    $headers = @{ "User-Agent" = "PowerShell" }
    if ($env:GITHUB_TOKEN) {
        $headers["Authorization"] = "token $env:GITHUB_TOKEN"
    }
    $response = Invoke-RestMethod -Uri $apiUrl -Headers $headers
    $version = $response.tag_name
    if ($version -match '^v(.+)$') {
        $version = $Matches[1]
    }
    return $version
}

function Get-FileHash256 {
    param([string]$Path)
    return (Get-FileHash -Path $Path -Algorithm SHA256).Hash.ToLower()
}

function Confirm-Checksum {
    param(
        [string]$TarballPath,
        [string]$ChecksumPath
    )
    $tarballName = Split-Path $TarballPath -Leaf
    $checksumLines = Get-Content $ChecksumPath
    $expected = $null
    foreach ($line in $checksumLines) {
        if ($line -match [regex]::Escape($tarballName)) {
            $expected = ($line -split '\s+')[0]
            break
        }
    }
    if (-not $expected) {
        Write-Error "inngestcl: err unable to find checksum for '$tarballName' in '$ChecksumPath'"
        throw "Checksum not found"
    }
    $actual = Get-FileHash256 $TarballPath
    if ($expected -ne $actual) {
        Write-Error "inngestcl: err checksum for '$tarballName' did not verify ${expected} vs ${actual}"
        throw "Checksum mismatch"
    }
}

function Expand-ArchiveFile {
    param(
        [string]$ArchivePath,
        [string]$DestinationPath
    )
    if ($ArchivePath -match '\.zip$') {
        Expand-Archive -Path $ArchivePath -DestinationPath $DestinationPath -Force
    }
    elseif ($ArchivePath -match '\.tar\.gz$|\.tgz$') {
        tar -xzf $ArchivePath -C $DestinationPath
    }
    elseif ($ArchivePath -match '\.tar$') {
        tar -xf $ArchivePath -C $DestinationPath
    }
    else {
        Write-Error "inngestcl: err unknown archive format for $ArchivePath"
        throw "Unknown archive format"
    }
}

function Install-Inngest {
    $version = $env:VERSION
    if (-not $version) {
        Write-Host "inngestcl: info checking GitHub for latest version"
        $version = Get-GitHubLatestVersion "inngest/$reponame"
    }
    $version = $version -replace '^v', ''

    $os = Get-OSName
    $arch = Get-ArchName
    $baseUrl = "${base}/${reponame}/releases/download/v${version}"
    $tarball = "${reponame}_${version}_${os}_${arch}"
    if ($os -eq "windows") {
        $tarball += ".zip"
    } else {
        $tarball += ".tar.gz"
    }
    $tarballUrl = "${baseUrl}/${tarball}"
    $checksum = "checksums.txt"
    $checksumUrl = "${baseUrl}/${checksum}"
    $binDir = Join-Path $PWD.Path $binname + "-install"
    $binexe = if ($os -eq "windows") { "$binname.exe" } else { $binname }

    $tmpdir = Join-Path $env:TEMP "inngest-install-$(Get-Random)"
    New-Item -ItemType Directory -Path $tmpdir | Out-Null

    Write-Host "inngestcl: debug downloading files into $tmpdir"

    $tarballPath = Join-Path $tmpdir $tarball
    $checksumPath = Join-Path $tmpdir $checksum

    Invoke-WebRequest -Uri $tarballUrl -OutFile $tarballPath
    Invoke-WebRequest -Uri $checksumUrl -OutFile $checksumPath

    Confirm-Checksum $tarballPath $checksumPath

    Expand-ArchiveFile $tarballPath $tmpdir

    Copy-Item (Join-Path $tmpdir $binexe) (Join-Path $PWD $binexe) -Force

    Write-Host "inngestcl: info installed $(Join-Path $PWD $binexe)"
    Remove-Item -Recurse -Force $tmpdir

    $fullPath = Join-Path $PWD $binexe
    Write-Host ""
    Write-Host "$binexe has been installed into $fullPath. To place $binexe into your PATH run:"
    Write-Host "    Move-Item '$fullPath' '$env:ProgramFiles\inngest\$binexe'" -ForegroundColor Cyan
}

Install-Inngest