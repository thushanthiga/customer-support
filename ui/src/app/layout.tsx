import "./globals.css";
export const metadata = { title: "Apptimate Assist · ERP Support", description: "Your workspace for ERP answers and insights" };
export default function Layout({ children }: {
    children: React.ReactNode;
}) { return <html lang="en"><body>{children}</body></html>; }
