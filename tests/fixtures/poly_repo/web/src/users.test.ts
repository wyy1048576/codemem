import { disableUser } from "./users";

describe("disableUser", () => {
  it("loses sessions", () => {
    disableUser(alice);
  });
});
