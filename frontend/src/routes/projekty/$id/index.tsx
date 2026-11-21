import { createFileRoute } from '@tanstack/react-router'
import { ProjectCardScreen } from '@/features/projects/ProjectCardScreen'

export const Route = createFileRoute('/projekty/$id/')({
  component: () => <ProjectCardScreen id={Route.useParams().id} />,
})
