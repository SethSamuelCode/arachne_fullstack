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
          
          <Card className="flex flex-col items-center">
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

          <Card className="mt-8 flex flex-col items-center">
            <CardHeader>
              <CardTitle>What is Arachne?</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="mb-4 text-center text-muted-foreground">
                Arachne is my personal project to build a research assistant. My idea was that i wanted my own jarvis from iron man with me so i can ask it questions and help me find information. I wanted to rival the expensive research assistants from OpenAi, Google and perplexity and build my own.
              </p>
              <p className="mb-4 text-center text-muted-foreground">
                After completing some study to get back into the IT space i found the wonders of AI. It has shown me many things and surprised me at almost every turn. Some research argues that ai is not sentient but i have to disagree. The way it speaks, understand and behaves is like it understands even if its just numbers at the end. There is nothing to prove humans do not operate the same way with chemical signals driving them. 
              </p>
              <p>
                This is my gift to myself and the world to help people do research better and faster and to prove if you want to you can do anything you want. 
              </p>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
