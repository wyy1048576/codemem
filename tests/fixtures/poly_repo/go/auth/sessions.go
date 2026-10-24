package auth

// RevokeSession deletes one session from the store.
func RevokeSession(id string) {
	store.Delete(id)
}
