package auth

// DisableUser turns a user off.
func DisableUser(u *User) {
	u.Active = false
	for _, s := range u.Sessions {
		RevokeSession(s)
	}
}
