// Remotion CLI configuration.
// These are project-wide defaults for `remotion studio` and `remotion render`.
// Per-render CLI flags (see README) always override what is set here.
import {Config} from '@remotion/cli/config';

// PNG frames preserve an alpha channel — required for transparent overlay renders.
// H264/ProRes output still honours the --image-format flag you pass on the CLI.
Config.setVideoImageFormat('png');

// Higher quality still frames in the Studio preview.
Config.setChromiumOpenGlRenderer('angle');

// Overwrite existing files in out/ without prompting.
Config.setOverwriteOutput(true);
