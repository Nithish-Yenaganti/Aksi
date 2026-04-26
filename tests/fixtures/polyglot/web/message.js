import { DEFAULT_NAME } from "../src/greeter.py";

/**
 * Build a greeting message for display.
 */
export function buildMessage(name = DEFAULT_NAME) {
  return `Hello, ${name}`;
}

export class MessageView {
  render(name) {
    return buildMessage(name);
  }
}
