import { Disposable } from './lifecycle';

export function openSession(id: string): Session {
  return new Session(id);
}

export const closeSession = (s: Session) => {
  s.close();
};

function* ids() {
  yield 1;
}

@injectable()
export abstract class Session extends Disposable implements Closable {
  private readonly onClose = () => this.fire('close');

  constructor(readonly id: string) {
    super();
  }

  @memoize
  get title(): string {
    const format = (t: string) => t.trim();
    return format(this.id);
  }

  abstract close(): void;
}

export interface Closable {
  close(): void;
}

export enum State { Open, Closed }

export default function () {
  return ids();
}
