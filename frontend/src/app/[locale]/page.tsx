import Link from "next/link";
import { Button, Card, CardHeader, CardTitle, CardContent } from "@/components/ui";
import { ROUTES } from "@/lib/constants";

export default function HomePage() {
  return (
    <div className="min-h-screen bg-background">
      <div className="container mx-auto py-16 px-4">
        <div className="text-center mb-12">
          <h1 className="text-4xl font-bold mb-4">
            Arachne 
          </h1>
          <p className="text-xl text-muted-foreground max-w-2xl mx-auto">
            Arachne research assistant
          </p>
        </div>

        <div className="max-w-5xl mx-auto">
          
          <Card>
            <CardHeader>
              <CardTitle>Authentication</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex gap-2">
                <Button asChild>
                  <Link href={ROUTES.LOGIN}>Login</Link>
                </Button>
                <Button variant="outline" asChild>
                  <Link href={ROUTES.REGISTER}>Register</Link>
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
