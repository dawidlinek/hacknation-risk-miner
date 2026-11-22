/**
 * Remotion CLI defaults for the promo renders.
 * Responsibility: codec, quality and GL settings shared by `studio` and every render.
 * Idempotency: n/a — pure configuration.
 */
import { Config } from '@remotion/cli/config';

Config.setVideoImageFormat('jpeg');
Config.setJpegQuality(95);
Config.setCodec('h264');
Config.setCrf(16);
Config.setOverwriteOutput(true);
// Light leaks and the shader transitions draw through WebGL2.
Config.setChromiumOpenGlRenderer('angle');
