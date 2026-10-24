import { revokeSession } from "./sessions";

export const disableUser = (user: User) => {
  user.active = false;
  user.sessions.forEach((s) => revokeSession(s));
};
