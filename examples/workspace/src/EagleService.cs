namespace Demo;

public class EagleService
{
    public bool Execute(string requestId)
    {
        return !string.IsNullOrWhiteSpace(requestId);
    }
}
