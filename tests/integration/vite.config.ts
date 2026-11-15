import frontend from '../../frontend/vite.config.ts'

// Reuse the actual frontend plugins, while preventing reads of the team's root .env.
export default { ...frontend, envDir: false }
