import { label } from "./label";

export class Widget {
  render(name) {
    return label(name);
  }
}

export function renderWidget(name) {
  return new Widget().render(name);
}
