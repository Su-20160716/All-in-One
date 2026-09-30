# Frontend build wrapper for this Windows machine.
# Why: esbuild.exe under node_modules lives inside the Desktop tree, which triggers a
#      local security policy; during build its temp-file removal is denied
#      (Access is denied / esbuild service crash).
#      If a copy of esbuild.exe exists outside the Desktop tree (under the user profile),
#      point ESBUILD_BINARY_PATH to it; otherwise fall back to the default esbuild.
$extEsbuild = Join-Path $HOME ".cache\esbuild\esbuild.exe"
if (Test-Path $extEsbuild) {
    $env:ESBUILD_BINARY_PATH = $extEsbuild
    Write-Host "[build] using external esbuild: $extEsbuild" -ForegroundColor DarkGray
}
npm run build
