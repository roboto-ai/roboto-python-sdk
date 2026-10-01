# Install the Roboto CLI on Windows, then run `roboto setup` to finish setting up this machine.
#
#   powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/roboto-ai/roboto-python-sdk/main/install.ps1 | iex"
#
# To pass options to `roboto setup`, run the script with them in PowerShell, e.g.:
#
#   & ([scriptblock]::Create((irm https://raw.githubusercontent.com/roboto-ai/roboto-python-sdk/main/install.ps1))) --skip-mcp
#
# Environment variables:
#
#   ROBOTO_VERSION                Release to install, e.g. 0.58.0. Defaults to the latest release. A release from
#                                 before `roboto setup` existed is installed without running it.
#   ROBOTO_INSTALL_DIR            Directory to install roboto.exe into. Defaults to ~\.local\bin.
#   ROBOTO_NO_MODIFY_PATH=1       Don't add the install directory to your user PATH.
#   ROBOTO_SKIP_SETUP=1           Don't run `roboto setup`.
#   ROBOTO_DOWNLOAD_URL           Download the release's files from this URL instead of GitHub, e.g. a mirror.
#                                 ROBOTO_VERSION is ignored when this is set.
#
# The script is one script block, run on the last line, so a download cut off partway through runs nothing. The block
# also keeps the script's variables and functions out of the PowerShell session that `irm | iex` runs it in.

& {
  $ErrorActionPreference = 'Stop'
  $ProgressPreference = 'SilentlyContinue'

  $ReleasesUrl = 'https://github.com/roboto-ai/roboto-python-sdk/releases'
  $Asset = 'roboto-windows-x86_64.exe'
  $ChecksumsFile = 'roboto-sha256sums.txt'

  # -- Output ------------------------------------------------------------

  function Write-Step($Message) {
    Write-Host "==> $Message"
  }

  function Write-Detail($Message) {
    Write-Host "    $Message"
  }

  function Write-InstallWarning($Message) {
    Write-Host "warning: $Message" -ForegroundColor Yellow
  }

  # -- Downloads ---------------------------------------------------------

  function Get-ReleaseBaseUrl {
    if ($env:ROBOTO_DOWNLOAD_URL) {
      return $env:ROBOTO_DOWNLOAD_URL.TrimEnd('/')
    }
    if ($env:ROBOTO_VERSION) {
      return "$ReleasesUrl/download/v$($env:ROBOTO_VERSION.TrimStart('v'))"
    }
    return "$ReleasesUrl/latest/download"
  }

  # Downloads $Url to $Destination. Returns $true on success, and $false when the file isn't there, because the server
  # answered 404 or a file:// URL names no file. Any other failure throws.
  function Save-Download($Url, $Destination) {
    $client = New-Object System.Net.WebClient
    try {
      $client.DownloadFile($Url, $Destination)
      return $true
    } catch {
      # PowerShell wraps what WebClient throws, and WebClient may wrap it again.
      for ($exception = $_.Exception; $exception; $exception = $exception.InnerException) {
        if ($exception -is [System.Net.WebException] -and $exception.Response -is [System.Net.HttpWebResponse] -and
            [int]$exception.Response.StatusCode -eq 404) {
          return $false
        }
        if ($exception -is [System.IO.FileNotFoundException] -or $exception -is [System.IO.DirectoryNotFoundException]) {
          return $false
        }
      }
      throw $_.Exception.GetBaseException()
    } finally {
      $client.Dispose()
    }
  }

  # Releases published before the checksum file existed can't be verified, so when the release has no checksum file,
  # the installer warns and goes on. Any other failure to download it, a checksum file with no entry for the download,
  # or a different checksum stops the install.
  function Confirm-Download($BaseUrl, $File, $WorkDir) {
    $checksums = Join-Path $WorkDir $ChecksumsFile
    try {
      $published = Save-Download "$BaseUrl/$ChecksumsFile" $checksums
    } catch {
      throw "couldn't download $BaseUrl/$ChecksumsFile ($($_.Exception.Message))."
    }
    if (-not $published) {
      Write-InstallWarning "this release publishes no $ChecksumsFile, so the download can't be verified."
      return
    }

    $expected = $null
    foreach ($line in Get-Content -LiteralPath $checksums) {
      $parts = @($line.Trim() -split '\s+')
      if ($parts.Count -eq 2 -and $parts[1].TrimStart('*') -eq $Asset) {
        $expected = $parts[0].ToLowerInvariant()
      }
    }
    if (-not $expected) {
      throw "$ChecksumsFile has no entry for $Asset."
    }

    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $File).Hash.ToLowerInvariant()
    if ($actual -ne $expected) {
      throw "the downloaded $Asset doesn't match its checksum in $ChecksumsFile (expected $expected, got $actual)."
    }
    Write-Detail "Verified the download's SHA-256 checksum."
  }

  # -- Install -----------------------------------------------------------

  # Returns whether `& $Roboto @Arguments` exits with status 0. Its output is discarded.
  function Test-CommandSuccess($Roboto, $Arguments) {
    # With 'Stop', PowerShell 5.1 stops at the first line the command writes to standard error, so a CLI that runs
    # but prints a warning would count as failed.
    $ErrorActionPreference = 'Continue'
    try {
      & $Roboto @Arguments *> $null
    } catch {
      # Windows can't start the file: it's missing, or it isn't a program Windows can run.
      return $false
    }
    return $LASTEXITCODE -eq 0
  }

  function Install-Cli($InstallDir, $WorkDir) {
    $baseUrl = Get-ReleaseBaseUrl
    $download = Join-Path $WorkDir $Asset

    Write-Step "Downloading $Asset"
    try {
      $found = Save-Download "$baseUrl/$Asset" $download
    } catch {
      throw "couldn't download $baseUrl/$Asset ($($_.Exception.Message))."
    }
    if (-not $found) {
      throw "couldn't download $baseUrl/$Asset (not found)."
    }
    Confirm-Download $baseUrl $download $WorkDir

    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    $target = Join-Path $InstallDir 'roboto.exe'
    # Staged in the install directory and renamed into place, so an interrupted install never leaves a partly written
    # roboto.exe behind.
    $staged = Join-Path $InstallDir ".roboto.$PID.tmp.exe"
    try {
      Copy-Item -LiteralPath $download -Destination $staged -Force
      # Run before it replaces anything, so a download that doesn't run leaves an existing roboto.exe in place.
      Write-Step 'Checking that the Roboto CLI runs'
      if (-not (Test-CommandSuccess $staged @('--version', '--suppress-upgrade-check'))) {
        throw "the downloaded $Asset doesn't run."
      }

      if (Test-Path -LiteralPath $target) {
        # Windows won't replace or delete a running roboto.exe, but it will rename one. The CLI deletes the renamed
        # copy the next time it runs, and `roboto upgrade` uses the same name.
        $replaced = Join-Path $InstallDir '.roboto.exe.old'
        Remove-Item -LiteralPath $replaced -Force -ErrorAction SilentlyContinue
        Move-Item -LiteralPath $target -Destination $replaced
        try {
          Move-Item -LiteralPath $staged -Destination $target
        } finally {
          # A finally block also runs on Ctrl-C, which skips catch blocks, so the old roboto.exe goes back whenever
          # the new one isn't in place.
          if (-not (Test-Path -LiteralPath $target)) {
            Move-Item -LiteralPath $replaced -Destination $target
          }
        }
        Remove-Item -LiteralPath $replaced -Force -ErrorAction SilentlyContinue
      } else {
        Move-Item -LiteralPath $staged -Destination $target
      }
    } finally {
      Remove-Item -LiteralPath $staged -Force -ErrorAction SilentlyContinue
    }
    Write-Detail "Installed $target"
    return $target
  }

  # -- PATH --------------------------------------------------------------

  # PATH entries may be in quotes, which cmd.exe accepts.
  function Test-SameDirectory($A, $B) {
    return $A.Trim('"').TrimEnd('\') -eq $B.TrimEnd('\')
  }

  # The directories a new terminal searches: the machine PATH, then the user PATH. Windows expands the variables in
  # them, such as %USERPROFILE%, as it reads them.
  function Get-NewTerminalPath {
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    return @("$machine;$user" -split ';' | Where-Object { $_ })
  }

  function Test-OnNewTerminalPath($Dir) {
    return [bool](Get-NewTerminalPath | Where-Object { Test-SameDirectory $_ $Dir })
  }

  # Adds $Dir to the front of the user PATH that new terminals read, unless they already search it. Returns $true when
  # it changed the PATH.
  function Add-ToUserPath($Dir) {
    if (Test-OnNewTerminalPath $Dir) {
      return $false
    }

    # Read and written unexpanded, as the registry value holds it, so entries such as %USERPROFILE%\bin keep working
    # when the variables they name change.
    $key = 'registry::HKEY_CURRENT_USER\Environment'
    $current = (Get-Item -LiteralPath $key).GetValue('Path', '', 'DoNotExpandEnvironmentNames')
    $entries = @($Dir) + @($current -split ';' | Where-Object { $_ })
    Set-ItemProperty -LiteralPath $key -Name Path -Type ExpandString -Value ($entries -join ';')

    # Writing the registry doesn't tell running programs that the environment changed; setting a user variable through
    # .NET does. Explorer then reloads the environment, so terminals opened from Explorer or the Start menu get the new
    # PATH. The variable is deleted right after.
    $notice = "RobotoInstaller$([guid]::NewGuid().ToString('N'))"
    [Environment]::SetEnvironmentVariable($notice, '1', 'User')
    [Environment]::SetEnvironmentVariable($notice, [NullString]::Value, 'User')
    return $true
  }

  # Returns the first roboto a new terminal would find before $Installed, or $null.
  function Find-EarlierRoboto($Installed) {
    $installDir = Split-Path -Parent $Installed
    $extensions = @($env:PATHEXT -split ';' | Where-Object { $_ })
    foreach ($entry in Get-NewTerminalPath) {
      if (Test-SameDirectory $entry $installDir) {
        return $null
      }
      $dir = $entry.Trim('"').TrimEnd('\')
      foreach ($extension in $extensions) {
        # Joined as text: Join-Path fails on an entry naming a drive that doesn't exist, such as an unmapped network
        # drive.
        $candidate = "$dir\roboto$extension"
        if (Test-Path -LiteralPath $candidate -PathType Leaf -ErrorAction SilentlyContinue) {
          return $candidate
        }
      }
    }
    return $null
  }

  # -- Main --------------------------------------------------------------

  $status = 0
  $pathChanged = $false
  $workDir = $null
  try {
    if (-not [Environment]::Is64BitOperatingSystem) {
      throw 'the Roboto CLI runs on 64-bit Windows only.'
    }
    # GitHub requires TLS 1.2, which older .NET Framework versions don't enable by default.
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

    $installDir = if ($env:ROBOTO_INSTALL_DIR) {
      # A relative directory is resolved against the current one, since PATH needs full paths.
      $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($env:ROBOTO_INSTALL_DIR)
    } else {
      Join-Path $HOME '.local\bin'
    }
    $workDir = Join-Path ([IO.Path]::GetTempPath()) "roboto-install-$([guid]::NewGuid().ToString('N'))"
    New-Item -ItemType Directory -Path $workDir | Out-Null

    $roboto = Install-Cli $installDir $workDir

    if ($env:ROBOTO_NO_MODIFY_PATH -eq '1') {
      if (-not (Test-OnNewTerminalPath $installDir)) {
        Write-InstallWarning "$installDir isn't on your PATH. Add it to run ``roboto`` from a new terminal."
      }
    } elseif (Add-ToUserPath $installDir) {
      Write-Detail "Added $installDir to your user PATH"
      $pathChanged = $true
    }
    # Only when new terminals search the install directory; otherwise the warning above already covers it.
    $earlier = if (Test-OnNewTerminalPath $installDir) { Find-EarlierRoboto $roboto }
    if ($earlier) {
      Write-InstallWarning "another ``roboto`` at $earlier comes first on your PATH, so typing ``roboto`` in a new terminal runs that one. Remove it or put $installDir earlier on your PATH."
    }
    # For `roboto setup` below, and for the rest of this session when `irm | iex` runs the script.
    $env:Path = "$installDir;$env:Path"

    if ($env:ROBOTO_SKIP_SETUP -ne '1') {
      # Releases from before `roboto setup` existed refuse the command.
      if (Test-CommandSuccess $roboto @('setup', '--help')) {
        # Run as a statement here, not in a function whose result is assigned: PowerShell would capture setup's
        # output, and setup needs the terminal to ask for an access token.
        & $roboto setup @args
        $status = $LASTEXITCODE
      } else {
        Write-Step "Skipping ``roboto setup``, which this release doesn't have"
      }
    }

    if ($pathChanged) {
      Write-Host ''
      Write-Host 'Open a new terminal to use the `roboto` command there.'
    }
  } catch {
    Write-Host "error: $($_.Exception.Message)" -ForegroundColor Red
    $status = 1
  } finally {
    if ($workDir) {
      Remove-Item -LiteralPath $workDir -Recurse -Force -ErrorAction SilentlyContinue
    }
  }

  # When the script runs from downloaded text, through `iex` or `[scriptblock]::Create`, `exit` ends the whole
  # PowerShell process, which closes the window when that's the user's own session; there the status goes to
  # $LASTEXITCODE instead. The script exits when it runs from a file, where `exit` ends only the script, and in a
  # PowerShell process started to run it, as the documented command does: started with -Command naming install.ps1,
  # and without -NoExit, which sessions such as Developer PowerShell for Visual Studio start with.
  $commandLine = [Environment]::GetCommandLineArgs()
  $startedToInstall = ($commandLine -match '^[-/](c|command)$') -and ($commandLine -like '*install.ps1*') -and
    -not ($commandLine -match '^[-/]noe(x|xi|xit)?$')
  $canExit = $PSCommandPath -or $startedToInstall
  if ($canExit) {
    exit $status
  }
  $global:LASTEXITCODE = $status
} @args
